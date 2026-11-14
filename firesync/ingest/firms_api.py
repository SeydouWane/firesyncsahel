"""NASA FIRMS area API: running season, recent months and NOAA-21.

Requires a free MAP_KEY (https://firms.modaps.eosdis.nasa.gov/api/map_key/),
read from FIRMS_MAP_KEY or the admin settings. For every sensor family the
standard-processing (SP) product is used as far as it exists, then the
near-real-time (NRT) product up to today (dates from the API's
data_availability endpoint). The API serves at most 5 days per request.

The API returns a rectangle: detections are clipped to the union of the
configured countries' administrative boundaries so that they match the
yearly country archives. Files land in data/raw/firms_api/ and are merged by
`processing.load_raw` (exact duplicates with the archives are dropped).
"""
from __future__ import annotations

import csv
import io
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import requests

from .. import config

log = logging.getLogger(__name__)
BASE = "https://firms.modaps.eosdis.nasa.gov"
API = BASE + "/api/area/csv/{key}/{src}/{bbox}/{days}/{day}"
FAMILIES = {
    "MODIS": ("MODIS_SP", "MODIS_NRT"),
    "VIIRS_SNPP": ("VIIRS_SNPP_SP", "VIIRS_SNPP_NRT"),
    "VIIRS_NOAA20": ("VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT"),
    "VIIRS_NOAA21": ("VIIRS_NOAA21_SP", "VIIRS_NOAA21_NRT"),
}
# NOAA-21 is absent from the yearly country archives: fetch its whole record
# (overlap with S-NPP since 2023 is needed to learn NOAA-21 -> S-NPP).
FAMILY_START = {"VIIRS_NOAA21": date(2023, 1, 1)}
MAX_DAYS = 5  # the area API accepts a day range of 1..5


def map_key() -> str:
    if config.FIRMS_MAP_KEY:
        return config.FIRMS_MAP_KEY
    try:
        from ..api import db
        return db.get_setting("firms_map_key", "") or ""
    except Exception:
        return ""


def key_status(key: str | None = None) -> dict:
    key = key or map_key()
    if not key:
        return {"configured": False}
    try:
        r = requests.get(f"{BASE}/mapserver/mapkey_status/?MAP_KEY={key}", timeout=30)
        return {"configured": True, **r.json()}
    except Exception as e:
        return {"configured": True, "error": str(e)}


def availability(key: str) -> dict[str, tuple[date, date]]:
    r = requests.get(f"{BASE}/api/data_availability/csv/{key}/all", timeout=60)
    r.raise_for_status()
    out = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        try:
            out[row["data_id"]] = (date.fromisoformat(row["min_date"]), date.fromisoformat(row["max_date"]))
        except (KeyError, ValueError):
            continue
    return out


def _region():
    """Union of admin units (prepared shapely geometry) + bbox string."""
    import shapely
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from . import boundaries
    gj = boundaries.load(1)
    if gj is None:
        boundaries.build()
        gj = boundaries.load(1)
    geom = unary_union([shape(f["geometry"]) for f in gj["features"]]).buffer(0.01)
    shapely.prepare(geom)
    x0, y0, x1, y1 = geom.bounds
    return geom, f"{x0:.3f},{y0:.3f},{x1:.3f},{y1:.3f}"


def _clip(text: str, geom) -> tuple[str, int]:
    import shapely
    lines = text.strip().splitlines()
    if len(lines) <= 1:
        return lines[0] + "\n" if lines else "", 0
    head = lines[0].split(",")
    ila, ilo = head.index("latitude"), head.index("longitude")
    rows = [ln.split(",") for ln in lines[1:]]
    lat = np.array([float(r[ila]) for r in rows])
    lon = np.array([float(r[ilo]) for r in rows])
    keep = shapely.contains_xy(geom, lon, lat)
    kept = [ln for ln, k in zip(lines[1:], keep) if k]
    return "\n".join([lines[0], *kept]) + "\n", len(kept)


def plan(avail: dict, start: date, end: date) -> list[tuple[str, date, int]]:
    jobs = []
    for fam, (sp, nrt) in FAMILIES.items():
        s0 = FAMILY_START.get(fam, start)
        segs = []
        if sp in avail:
            a, b = avail[sp]
            segs.append((sp, max(s0, a), min(b, end)))
            s0 = max(s0, b + timedelta(days=1))
        if nrt in avail:
            a, b = avail[nrt]
            segs.append((nrt, max(s0, a), min(b, end)))
        for src, a, b in segs:
            d = a
            while d <= b:
                days = min(MAX_DAYS, (b - d).days + 1)
                jobs.append((src, d, days))
                d += timedelta(days=days)
    return jobs


def update(start: date | None = None, end: date | None = None, progress=None, workers: int = 4) -> dict:
    key = map_key()
    if not key:
        return {"status": "skipped", "reason": "FIRMS_MAP_KEY missing"}
    start = start or date(config.LAST_ARCHIVE_YEAR + 1, 1, 1)
    end = end or date.today()
    geom, bbox = _region()
    avail = availability(key)
    jobs = plan(avail, start, end)
    out_dir = config.RAW / "firms_api"
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {"files": 0, "rows": 0, "skipped": 0, "errors": 0}

    def one(job):
        src, d0, days = job
        dest = out_dir / f"{src}_{d0.isoformat()}_{days}d.csv"
        fresh = src.endswith("NRT") and (end - d0).days < 12  # NRT tail is still filling
        if dest.exists() and not fresh:
            return "skipped", 0
        url = API.format(key=key, src=src, bbox=bbox, days=days, day=d0.isoformat())
        for attempt in range(4):
            try:
                r = requests.get(url, timeout=120)
                if r.status_code == 200 and r.text.startswith("latitude"):
                    txt, n = _clip(r.text, geom)
                    dest.write_text(txt)
                    return "ok", n
                if r.status_code == 429 or "Exceeding" in r.text:
                    time.sleep(20)
                    continue
                return f"error {r.status_code}: {r.text[:120]}", 0
            except requests.RequestException as e:
                err = str(e)
                time.sleep(3 * (attempt + 1))
        return f"error {err}", 0

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (status, n) in enumerate(ex.map(one, jobs)):
            if status == "ok":
                stats["files"] += 1
                stats["rows"] += n
            elif status == "skipped":
                stats["skipped"] += 1
            else:
                stats["errors"] += 1
                log.warning("FIRMS API %s", status)
            if progress:
                progress(i + 1, len(jobs))
    log.info("FIRMS API update: %s", stats)
    return {"status": "ok", "requests": len(jobs), **stats, "period": [str(start), str(end)]}
