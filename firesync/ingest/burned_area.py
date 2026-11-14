"""MODIS MCD64A1 v061 burned area -> weekly burned km² per H3 model cell.

MCD64A1 is a single-sensor (MODIS) product whose algorithm does not change in
2012, so it is an independent yardstick to check that the harmonised
active-fire series has no artificial step when VIIRS arrives.

Monthly Burn_Date COGs are read anonymously from Microsoft Planetary Computer
(windowed reads over the region only). Output: data/processed/burned_week.parquet
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import polars as pl

from .. import config
from ..config import GRID, WEEKS_PER_YEAR
from ..grid import latlng_to_cells

log = logging.getLogger(__name__)
OUT = config.PROCESSED / "burned_week.parquet"
R_SIN = 6371007.181
PIX_KM2 = (463.312716528 ** 2) / 1e6
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"


def _token() -> str:
    # SAS token of the storage container that hosts the MODIS v061 COGs
    url = "https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs"
    return json.load(urllib.request.urlopen(url, timeout=60))["token"]


def _sin_window(ds, bbox):
    """Pixel window of a sinusoidal tile covering a lon/lat bbox."""
    lon0, lat0, lon1, lat1 = bbox
    lats = np.radians(np.array([lat0, lat1, lat0, lat1, (lat0 + lat1) / 2]))
    lons = np.radians(np.array([lon0, lon0, lon1, lon1, lon0]))
    xs = np.concatenate([R_SIN * lons * np.cos(lats), [R_SIN * np.radians(lon1) * np.cos(lats[-1])]])
    ys = R_SIN * np.concatenate([lats, [lats[-1]]])
    inv = ~ds.transform
    cols, rows = zip(*[inv * (x, y) for x, y in zip(xs, ys)])
    c0, c1 = max(0, int(min(cols)) - 2), min(ds.width, int(max(cols)) + 3)
    r0, r1 = max(0, int(min(rows)) - 2), min(ds.height, int(max(rows)) + 3)
    if c0 >= c1 or r0 >= r1:
        return None
    from rasterio.windows import Window
    return Window(c0, r0, c1 - c0, r1 - r0)


def _read_item(href: str, token: str, bbox, year: int, cells: set[int]) -> pl.DataFrame | None:
    import rasterio
    for attempt in range(3):
        try:
            with rasterio.open(f"{href}?{token}") as ds:
                win = _sin_window(ds, bbox)
                if win is None:
                    return None
                arr = ds.read(1, window=win)
                tr = ds.window_transform(win)
            break
        except Exception as e:  # transient HTTP errors
            if attempt == 2:
                log.warning("MCD64A1 read failed %s: %s", href, e)
                return None
            time.sleep(3)
    rows, cols = np.nonzero(arr > 0)
    if rows.size == 0:
        return None
    doy = arr[rows, cols].astype(int)
    x = tr.c + (cols + 0.5) * tr.a
    y = tr.f + (rows + 0.5) * tr.e
    lat = np.degrees(y / R_SIN)
    lon = np.degrees(x / (R_SIN * np.cos(np.radians(lat))))
    inb = (lon >= bbox[0]) & (lon <= bbox[2]) & (lat >= bbox[1]) & (lat <= bbox[3])
    lat, lon, doy = lat[inb], lon[inb], doy[inb]
    if lat.size == 0:
        return None
    c5 = latlng_to_cells(lat, lon, GRID.model_res)
    dates = [date(year, 1, 1) + timedelta(days=int(d) - 1) for d in doy]
    yrs = np.array([d.year for d in dates], dtype=np.int16)
    wk = np.clip((doy - 1) // 7, 0, WEEKS_PER_YEAR - 1).astype(np.int8)
    df = pl.DataFrame({"h3_5": c5, "year": yrs, "week": wk})
    if cells:
        df = df.filter(pl.col("h3_5").is_in(list(cells)))
    return df.group_by(["h3_5", "year", "week"]).agg((pl.len() * PIX_KM2).alias("ba_km2"))


def build(first_year: int = 2001, last_year: int | None = None, workers: int = 6,
          progress=None) -> dict:
    from pystac_client import Client

    last_year = last_year or config.LAST_ARCHIVE_YEAR
    det = pl.read_parquet(config.PROCESSED / "detections.parquet", columns=["lat", "lon"])
    bbox = (det["lon"].min() - 0.1, det["lat"].min() - 0.1,
            det["lon"].max() + 0.1, det["lat"].max() + 0.1)
    cells = set(pl.read_parquet(config.PROCESSED / "model_week.parquet", columns=["h3_5"])
                ["h3_5"].unique().to_list())
    cat = Client.open(PC_STAC)
    items = list(cat.search(collections=["modis-64A1-061"], bbox=list(bbox),
                            datetime=f"{first_year}-01-01/{last_year}-12-31").items())
    log.info("MCD64A1 items: %d", len(items))
    token = _token()
    jobs = []
    for it in items:
        yr =int(str(it.properties.get("start_datetime") or it.datetime)[:4])
        jobs.append((it.assets["Burn_Date"].href, yr))
    frames = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_read_item, h, token, bbox, y, cells) for h, y in jobs]
        for i, f in enumerate(futs):
            r = f.result()
            if r is not None:
                frames.append(r)
            if progress:
                progress(i + 1, len(futs))
    if not frames:
        raise RuntimeError("no MCD64A1 data could be read (network or token issue)")
    out = (pl.concat(frames).group_by(["h3_5", "year", "week"]).agg(pl.col("ba_km2").sum())
           .sort(["h3_5", "year", "week"]))
    out.write_parquet(OUT)
    meta = {"product": "MODIS MCD64A1 v061 Burn_Date (500 m)", "items": len(items),
            "years": [first_year, last_year], "rows": out.height,
            "via": "Microsoft Planetary Computer"}
    (config.PROCESSED / "burned_meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def load() -> pl.DataFrame | None:
    return pl.read_parquet(OUT) if OUT.exists() else None
