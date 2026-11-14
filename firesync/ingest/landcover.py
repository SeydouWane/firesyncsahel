"""Land-cover fractions per H3 model cell, used to stratify the harmonisation.

Two sources share one output (data/processed/landcover_h3_5.parquet):

* ``mcd12q1`` — MODIS MCD12Q1 v061 (IGBP, LC_Type1), the reference product of
  the method. It is distributed by LP DAAC and needs a NASA Earthdata login:
  download the GeoTIFF(s) covering the region (AppEEARS or LP DAAC) into
  ``data/raw/mcd12q1/`` and run ``python -m firesync landcover --source mcd12q1``.
* ``esa-cci`` — ESA CCI Land Cover 300 m, read anonymously from Microsoft
  Planetary Computer. Used automatically when no MCD12Q1 file is present; the
  source actually used is recorded in the output and shown in the app.

Both are mapped to the same six groups so the model does not depend on the
source.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path

import numpy as np
import polars as pl

from .. import config
from ..config import GRID
from ..grid import latlng_to_cells

log = logging.getLogger(__name__)
OUT = config.PROCESSED / "landcover_h3_5.parquet"
META = config.PROCESSED / "landcover_meta.json"
GROUPS = ["forest", "savanna", "shrubland", "grassland", "cropland", "other"]
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"

# ESA CCI LCCS class -> group index
_CCI = {}
for v in (10, 11, 12, 20, 30):
    _CCI[v] = 4
for v in (40, 100, 110):
    _CCI[v] = 1
for v in (50, 60, 61, 62, 70, 71, 72, 80, 81, 82, 90, 160, 170):
    _CCI[v] = 0
for v in (120, 121, 122):
    _CCI[v] = 2
for v in (130, 140, 180):
    _CCI[v] = 3
for v in (150, 151, 152, 153, 190, 200, 201, 202, 210, 220):
    _CCI[v] = 5

# MODIS IGBP (LC_Type1) -> group index
_IGBP = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 2, 7: 2, 8: 1, 9: 1, 10: 3, 11: 3,
         12: 4, 14: 4, 13: 5, 15: 5, 16: 5, 17: 5}


def _lut(mapping: dict[int, int], size: int = 256) -> np.ndarray:
    lut = np.full(size, 255, dtype=np.uint8)
    for k, v in mapping.items():
        lut[k] = v
    return lut


def _aggregate(lat: np.ndarray, lon: np.ndarray, grp: np.ndarray, cells_needed: set[int]
               ) -> pl.DataFrame:
    ok = grp < 255
    lat, lon, grp = lat[ok], lon[ok], grp[ok]
    c5 = latlng_to_cells(lat, lon, GRID.model_res)
    df = pl.DataFrame({"h3_5": c5, "g": grp.astype(np.int8)})
    if cells_needed:
        df = df.filter(pl.col("h3_5").is_in(list(cells_needed)))
    cnt = df.group_by(["h3_5", "g"]).len().pivot(on="g", index="h3_5", values="len")
    for i in range(len(GROUPS)):
        if str(i) not in cnt.columns:
            cnt = cnt.with_columns(pl.lit(0).alias(str(i)))
    cnt = cnt.fill_null(0)
    tot = sum(pl.col(str(i)) for i in range(len(GROUPS)))
    return cnt.select(
        "h3_5", *[(pl.col(str(i)) / tot).alias(f"lc_{g}") for i, g in enumerate(GROUPS)]
    ).with_columns(pl.concat_list([f"lc_{g}" for g in GROUPS]).list.arg_max()
                   .alias("lc_major").cast(pl.Int8))


def _region_bbox(margin: float = 0.3) -> tuple[float, float, float, float]:
    det = pl.read_parquet(config.PROCESSED / "detections.parquet", columns=["lat", "lon"])
    return (det["lon"].min() - margin, det["lat"].min() - margin,
            det["lon"].max() + margin, det["lat"].max() + margin)


def _model_cells() -> set[int]:
    mt = pl.read_parquet(config.PROCESSED / "model_week.parquet", columns=["h3_5"])
    return set(mt["h3_5"].unique().to_list())


def from_esa_cci(year: int = 2015, step: int = 2) -> pl.DataFrame:
    import rasterio
    from rasterio.windows import from_bounds
    from pystac_client import Client

    bbox = _region_bbox()
    cat = Client.open(PC_STAC)
    items = list(cat.search(collections=["esa-cci-lc"], bbox=list(bbox),
                            datetime=f"{year}-01-01/{year}-12-31").items())
    if not items:
        raise RuntimeError("no ESA CCI item for region/year")
    tok = json.load(urllib.request.urlopen(
        "https://planetarycomputer.microsoft.com/api/sas/v1/token/esa-cci-lc"))["token"]
    lats, lons, grps = [], [], []
    lut = _lut(_CCI)
    for it in items:
        href = it.assets["lccs_class"].href
        with rasterio.open(f"{href}?{tok}") as ds:
            l, b, r, t = ds.bounds
            win = from_bounds(max(bbox[0], l), max(bbox[1], b), min(bbox[2], r), min(bbox[3], t),
                              ds.transform)
            arr = ds.read(1, window=win)[::step, ::step]
            tr = ds.window_transform(win)
            rows, cols = np.indices(arr.shape)
            xs = tr.c + (cols * step + 0.5) * tr.a
            ys = tr.f + (rows * step + 0.5) * tr.e
            lats.append(ys.ravel()); lons.append(xs.ravel()); grps.append(lut[arr.ravel()])
    out = _aggregate(np.concatenate(lats), np.concatenate(lons), np.concatenate(grps),
                     _model_cells())
    _write(out, {"source": "esa-cci", "product": "ESA CCI Land Cover v2 (300 m)",
                 "year": year, "via": "Microsoft Planetary Computer"})
    return out


R_SIN = 6371007.181
TILE_M = 1111950.5197665
PIX_M = TILE_M / 2400
LPDAAC = "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/MCD12Q1.061"


def _hdf_tile_latlon(path: Path, step: int = 2):
    """Read LC_Type1 from an MCD12Q1 HDF4 tile and return lat, lon, class."""
    import re
    from pyhdf.SD import SD, SDC

    m = re.search(r"\.h(\d\d)v(\d\d)\.", path.name)
    h, v = int(m.group(1)), int(m.group(2))
    sd = SD(str(path), SDC.READ)
    arr = sd.select("LC_Type1")[:][::step, ::step]
    sd.end()
    rows, cols = np.indices(arr.shape)
    x = -20015109.354 + h * TILE_M + (cols * step + 0.5) * PIX_M
    y = 10007554.677 - v * TILE_M - (rows * step + 0.5) * PIX_M
    lat = np.degrees(y / R_SIN)
    lon = np.degrees(x / (R_SIN * np.cos(np.radians(lat))))
    return lat.ravel(), lon.ravel(), arr.ravel()


def tiles_for_bbox(bbox) -> list[tuple[int, int]]:
    lon0, lat0, lon1, lat1 = bbox
    out = set()
    for lat in np.linspace(lat0, lat1, 12):
        for lon in np.linspace(lon0, lon1, 12):
            x = R_SIN * np.radians(lon) * np.cos(np.radians(lat))
            y = R_SIN * np.radians(lat)
            out.add((int((x + 20015109.354) // TILE_M), int((10007554.677 - y) // TILE_M)))
    return sorted(out)


def download_mcd12q1(year: int = 2016) -> list[Path]:
    """Download the MCD12Q1 tiles covering the region from LP DAAC (Earthdata login)."""
    import requests
    from .earthdata import download, session

    bbox = _region_bbox(0.0)
    tiles = tiles_for_bbox(bbox)
    r = requests.get("https://cmr.earthdata.nasa.gov/search/granules.json", timeout=60, params={
        "short_name": "MCD12Q1", "version": "061", "page_size": 50,
        "temporal": f"{year}-01-01T00:00:00Z,{year}-12-31T23:59:59Z",
        "bounding_box": ",".join(f"{v:.3f}" for v in bbox)})
    r.raise_for_status()
    hrefs = [l["href"] for e in r.json()["feed"]["entry"] for l in e.get("links", [])
             if l.get("href", "").endswith(".hdf") and l["href"].startswith("https")
             and "s3" not in l["href"].split("/")[2]]
    s = session()
    out = []
    for href in sorted(set(hrefs)):
        name = href.rsplit("/", 1)[1]
        if not any(f".h{h:02d}v{v:02d}." in name for h, v in tiles):
            continue
        out.append(download(href, config.RAW / "mcd12q1" / name, s))
    if not out:
        raise RuntimeError(f"no MCD12Q1 tile found for {tiles} in {year}")
    return out


def from_mcd12q1(folder: Path | None = None) -> pl.DataFrame:
    """Read MCD12Q1 LC_Type1 (HDF4 tiles or GeoTIFF exports) from data/raw/mcd12q1."""
    folder = folder or (config.RAW / "mcd12q1")
    hdfs = sorted(folder.glob("MCD12Q1*.hdf"))
    tifs = sorted(folder.glob("*.tif")) + sorted(folder.glob("*.tiff"))
    files = hdfs + tifs
    if not files:
        raise FileNotFoundError(f"no MCD12Q1 file in {folder}")
    lut = _lut(_IGBP)
    lats, lons, grps = [], [], []
    bbox = _region_bbox()
    for f in hdfs:
        lat, lon, cls = _hdf_tile_latlon(f)
        keep = (lon >= bbox[0]) & (lon <= bbox[2]) & (lat >= bbox[1]) & (lat <= bbox[3])
        lats.append(lat[keep]); lons.append(lon[keep]); grps.append(lut[cls[keep]])
    for f in tifs:
        import rasterio
        from rasterio.warp import transform as rio_transform
        with rasterio.open(f) as ds:
            arr = ds.read(1)
            rows, cols = np.indices(arr.shape)
            xs, ys = rasterio.transform.xy(ds.transform, rows.ravel(), cols.ravel())
            lon, lat = rio_transform(ds.crs, "EPSG:4326", np.asarray(xs), np.asarray(ys))
            lats.append(np.asarray(lat)); lons.append(np.asarray(lon))
            grps.append(lut[np.clip(arr.ravel(), 0, 255)])
    out = _aggregate(np.concatenate(lats), np.concatenate(lons), np.concatenate(grps),
                     _model_cells())
    _write(out, {"source": "mcd12q1", "product": "MODIS MCD12Q1 v061 LC_Type1 (IGBP, 500 m)",
                 "files": [p.name for p in files]})
    return out


def _write(df: pl.DataFrame, meta: dict) -> None:
    df.write_parquet(OUT)
    meta["groups"] = GROUPS
    meta["cells"] = df.height
    META.write_text(json.dumps(meta, indent=2))
    log.info("land cover written: %s (%d cells)", meta["source"], df.height)


def build(source: str = "auto", year: int = 2016) -> dict:
    if source in ("auto", "mcd12q1"):
        try:
            if not list((config.RAW / "mcd12q1").glob("MCD12Q1*.hdf")):
                try:
                    download_mcd12q1(year)
                except Exception as e:  # no credentials / network
                    log.warning("MCD12Q1 download skipped: %s", e)
            from_mcd12q1()
            return json.loads(META.read_text())
        except FileNotFoundError:
            if source == "mcd12q1":
                raise
            log.info("no MCD12Q1 file, falling back to ESA CCI")
    from_esa_cci()
    return json.loads(META.read_text())


def load() -> pl.DataFrame | None:
    return pl.read_parquet(OUT) if OUT.exists() else None


def meta() -> dict:
    return json.loads(META.read_text()) if META.exists() else {"source": None}
