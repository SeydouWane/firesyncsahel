"""MODIS MOD13A1 v061 NDVI (16-day, 500 m) -> end-of-rainy-season fuel per cell.

In the Sahel, the herbaceous biomass grown during the rainy season (July-
October) is the fuel of the following dry-season fires. The maximum NDVI of
the August-October composites is a classic proxy of that fuel load; its
anomaly against the cell's own mean tells whether the coming season has more
or less fuel than usual.

Read anonymously from Microsoft Planetary Computer (windowed COG reads).
Output: data/processed/ndvi_fuel.parquet (h3_5, year, ndvi_max, ndvi_anom)
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import polars as pl

from .. import config
from ..config import GRID
from ..grid import latlng_to_cells
from .burned_area import PC_STAC, R_SIN, _sin_window, _token

log = logging.getLogger(__name__)
OUT = config.PROCESSED / "ndvi_fuel.parquet"
RAW_OUT = config.PROCESSED / "ndvi_cell.parquet"


def _read(href: str, token: str, bbox, cells: set[int], step: int = 2) -> pl.DataFrame | None:
    import rasterio
    for attempt in range(3):
        try:
            with rasterio.open(f"{href}?{token}") as ds:
                win = _sin_window(ds, bbox)
                if win is None:
                    return None
                arr = ds.read(1, window=win)[::step, ::step].astype(np.float32)
                tr = ds.window_transform(win)
            break
        except Exception as e:
            if attempt == 2:
                log.warning("NDVI read failed %s: %s", href, e)
                return None
            time.sleep(3)
    rows, cols = np.nonzero(arr > -2000)  # fill value -3000
    if rows.size == 0:
        return None
    x = tr.c + (cols * step + 0.5) * tr.a
    y = tr.f + (rows * step + 0.5) * tr.e
    lat = np.degrees(y / R_SIN)
    lon = np.degrees(x / (R_SIN * np.cos(np.radians(lat))))
    inb = (lon >= bbox[0]) & (lon <= bbox[2]) & (lat >= bbox[1]) & (lat <= bbox[3])
    c5 = latlng_to_cells(lat[inb], lon[inb], GRID.model_res)
    df = pl.DataFrame({"h3_5": c5, "ndvi": arr[rows, cols][inb] / 10000.0})
    if cells:
        df = df.filter(pl.col("h3_5").is_in(list(cells)))
    return df.group_by("h3_5").agg(pl.col("ndvi").mean())


def build(first_year: int = 2000, last_year: int | None = None, workers: int = 6, progress=None) -> dict:
    from datetime import date
    from pystac_client import Client
    last_year = last_year or date.today().year
    det = pl.read_parquet(config.PROCESSED / "detections.parquet", columns=["lat", "lon"])
    bbox = (det["lon"].min() - 0.1, det["lat"].min() - 0.1, det["lon"].max() + 0.1, det["lat"].max() + 0.1)
    cells = set(pl.read_parquet(config.PROCESSED / "model_week.parquet", columns=["h3_5"])["h3_5"].unique().to_list())
    cat = Client.open(PC_STAC)
    jobs = []
    for yr in range(first_year, last_year + 1):
        items = cat.search(collections=["modis-13A1-061"], bbox=list(bbox),
                           datetime=f"{yr}-08-01/{yr}-10-31").items()
        for it in items:
            if not it.id.startswith("MOD13A1"):  # Terra composites only (one per 16 days)
                continue
            a = it.assets.get("500m_16_days_NDVI")
            if a:
                jobs.append((a.href, yr, str(it.properties.get("start_datetime") or it.datetime)[:10]))
    log.info("NDVI composites: %d", len(jobs))
    token = _token()
    frames = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [(y, d, ex.submit(_read, h, token, bbox, cells)) for h, y, d in jobs]
        for i, (y, d, f) in enumerate(futs):
            r = f.result()
            if r is not None:
                frames.append(r.with_columns(pl.lit(y, pl.Int16).alias("year"), pl.lit(d).alias("date")))
            if progress:
                progress(i + 1, len(futs))
    raw = pl.concat(frames)
    raw.write_parquet(RAW_OUT)
    fuel = raw.group_by(["h3_5", "year"]).agg(pl.col("ndvi").max().alias("ndvi_max"))
    fuel = fuel.with_columns((pl.col("ndvi_max") - pl.col("ndvi_max").mean().over("h3_5")).alias("ndvi_anom"))
    fuel.sort(["h3_5", "year"]).write_parquet(OUT)
    meta = {"product": "MODIS MOD13A1 v061 NDVI (16-day, 500 m)", "composites": len(jobs),
            "years": sorted(fuel["year"].unique().to_list()), "via": "Microsoft Planetary Computer"}
    (config.PROCESSED / "ndvi_meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def load() -> pl.DataFrame | None:
    return pl.read_parquet(OUT) if OUT.exists() else None
