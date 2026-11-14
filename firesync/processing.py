"""Raw FIRMS CSV -> clean detections table -> weekly hexagon aggregates.

Outputs (data/processed):
  detections.parquet   one row per active-fire detection, all sensors
  fine_week.parquet    counts per (H3 res-7 cell, year, week, sensor)
  model_week.parquet   full grid (H3 res-5 cell x year x week) with per-sensor
                       counts and FRP, the input of the harmonisation model
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import polars as pl

from . import config
from .config import GRID, WEEKS_PER_YEAR
from .grid import latlng_to_cells, parents

log = logging.getLogger(__name__)

DET_PATH = config.PROCESSED / "detections.parquet"
FINE_PATH = config.PROCESSED / "fine_week.parquet"
MODEL_PATH = config.PROCESSED / "model_week.parquet"

SENSOR_ORDER = ["MODIS_T", "MODIS_A", "VIIRS_SNPP", "VIIRS_N20", "VIIRS_N21"]

_VIIRS_SAT = {"N": "VIIRS_SNPP", "NPP": "VIIRS_SNPP", "N20": "VIIRS_N20", "1": "VIIRS_N20",
              "J1": "VIIRS_N20", "N21": "VIIRS_N21", "2": "VIIRS_N21", "J2": "VIIRS_N21"}


def _read_csv(path: Path) -> pl.DataFrame:
    df = pl.read_csv(path, infer_schema_length=0)  # everything as string first
    if df.height == 0:
        return df
    inst = df["instrument"][0] if "instrument" in df.columns else (
        "MODIS" if "brightness" in df.columns else "VIIRS")
    if inst == "MODIS":
        sensor = (pl.when(pl.col("satellite").is_in(["Terra", "T"])).then(pl.lit("MODIS_T"))
                  .otherwise(pl.lit("MODIS_A")))
        conf = pl.col("confidence").cast(pl.Float64)
        conf_class = (pl.when(conf < 30).then(pl.lit("l"))
                      .when(conf < 80).then(pl.lit("n")).otherwise(pl.lit("h")))
    else:
        sensor = pl.col("satellite").replace_strict(_VIIRS_SAT, default="VIIRS_SNPP")
        conf_class = pl.col("confidence").str.to_lowercase().str.slice(0, 1)
    out = df.select(
        sensor.alias("sensor"),
        pl.col("latitude").cast(pl.Float64).alias("lat"),
        pl.col("longitude").cast(pl.Float64).alias("lon"),
        pl.col("acq_date").str.to_date("%Y-%m-%d").alias("date"),
        pl.col("acq_time").str.zfill(4).alias("hhmm"),
        pl.col("frp").cast(pl.Float64).alias("frp"),
        pl.col("scan").cast(pl.Float64).alias("scan"),
        pl.col("track").cast(pl.Float64).alias("track"),
        conf_class.alias("conf"),
        pl.col("daynight").alias("daynight"),
        (pl.col("type").cast(pl.Int8) if "type" in df.columns else pl.lit(0, pl.Int8)).alias("type"),
    )
    return out


def load_raw(raw_dir: Path | None = None) -> pl.DataFrame:
    raw_dir = raw_dir or (config.RAW / "firms")
    files = sorted(raw_dir.rglob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no FIRMS CSV under {raw_dir}; run `python -m firesync download`")
    frames = [f for f in (_read_csv(p) for p in files) if f.height]
    # NRT/API downloads (VIIRS NOAA-21, current season) live under raw/firms_api
    api_dir = config.RAW / "firms_api"
    if api_dir.exists():
        for p in sorted(api_dir.rglob("*.csv")):
            f = _read_csv(p)
            if f.height:
                frames.append(f)
    df = pl.concat(frames, how="vertical_relaxed")
    log.info("raw detections: %d from %d files", df.height, len(files))
    return df


def clean(df: pl.DataFrame, drop_low_conf: bool = True) -> pl.DataFrame:
    """Keep presumed vegetation fires, drop low confidence, add time & grid keys."""
    n0 = df.height
    df = df.filter(pl.col("type") == 0)
    if drop_low_conf:
        df = df.filter(pl.col("conf") != "l")
    # archive files overlap with NRT pulls -> drop exact duplicates
    df = df.unique(subset=["sensor", "lat", "lon", "date", "hhmm"], keep="first")
    df = df.with_columns(
        (pl.col("hhmm").str.slice(0, 2).cast(pl.Int32) * 60
         + pl.col("hhmm").str.slice(2, 2).cast(pl.Int32)).alias("utc_min"),
        pl.col("date").dt.year().cast(pl.Int16).alias("year"),
        pl.col("date").dt.ordinal_day().cast(pl.Int16).alias("doy"),
    ).with_columns(
        ((pl.col("doy") - 1) // 7).clip(0, WEEKS_PER_YEAR - 1).cast(pl.Int8).alias("week"),
        ((pl.col("utc_min") / 60.0 + pl.col("lon") / 15.0) % 24).alias("solar_hour"),
    )
    lat = df["lat"].to_numpy()
    lon = df["lon"].to_numpy()
    c7 = latlng_to_cells(lat, lon, GRID.fine_res)
    c5 = parents(c7, GRID.model_res)
    c3 = parents(c5, GRID.coarse_res)
    df = df.with_columns(pl.Series("h3_7", c7), pl.Series("h3_5", c5), pl.Series("h3_3", c3))
    log.info("clean detections: %d (dropped %d)", df.height, n0 - df.height)
    return df.drop("hhmm").sort(["date", "utc_min"])


def week_days(year: int, week: int) -> int:
    """Number of days of calendar `week` (0..51) in `year` (week 51 has 8-9)."""
    if week < WEEKS_PER_YEAR - 1:
        return 7
    leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
    return (366 if leap else 365) - 7 * (WEEKS_PER_YEAR - 1)


def sensor_coverage(det: pl.DataFrame) -> pl.DataFrame:
    """First/last date each sensor actually has data in the archive."""
    return (det.group_by("sensor").agg(pl.col("date").min().alias("first"),
                                       pl.col("date").max().alias("last"),
                                       pl.len().alias("n"))
            .sort("sensor"))


def build_fine(det: pl.DataFrame) -> pl.DataFrame:
    return (det.group_by(["h3_7", "year", "week", "sensor"])
            .agg(pl.len().cast(pl.Int32).alias("n"), pl.col("frp").sum().alias("frp"))
            .sort(["year", "week", "h3_7"]))


def build_model_table(det: pl.DataFrame) -> pl.DataFrame:
    """Dense res-5 cell x year x week table with per-sensor counts and FRP."""
    agg = (det.group_by(["h3_5", "year", "week", "sensor"])
           .agg(pl.len().cast(pl.Int32).alias("n"),
                pl.col("frp").sum().alias("frp"),
                (pl.col("daynight") == "N").sum().cast(pl.Int32).alias("n_night")))
    wide = agg.pivot(on="sensor", index=["h3_5", "year", "week"],
                     values=["n", "frp", "n_night"], aggregate_function="sum")
    # normalise column names: n_MODIS_T, frp_MODIS_T, ...
    ren = {}
    for c in wide.columns:
        for s in SENSOR_ORDER:
            for v in ("n", "frp", "n_night"):
                if c in (f"{v}_{s}", f'{v}_sensor_{s}', f'{{"{v}","{s}"}}'):
                    ren[c] = f"{v}_{s}"
    wide = wide.rename(ren)
    cells = det.select("h3_5", "h3_3").unique()
    years = sorted(det["year"].unique().to_list())
    grid = (cells.join(pl.DataFrame({"year": pl.Series(years, dtype=pl.Int16)}), how="cross")
            .join(pl.DataFrame({"week": pl.Series(range(WEEKS_PER_YEAR), dtype=pl.Int8)}),
                  how="cross"))
    full = grid.join(wide, on=["h3_5", "year", "week"], how="left")
    for s in SENSOR_ORDER:
        for v, dt in (("n", pl.Int32), ("frp", pl.Float64), ("n_night", pl.Int32)):
            col = f"{v}_{s}"
            if col not in full.columns:
                full = full.with_columns(pl.lit(0, dt).alias(col))
            full = full.with_columns(pl.col(col).fill_null(0).cast(dt))
    full = full.with_columns(
        pl.struct(["year", "week"]).map_elements(lambda r: week_days(r["year"], r["week"]),
                                                 return_dtype=pl.Int8).alias("ndays"))
    return full.sort(["h3_5", "year", "week"])


def run(raw_dir: Path | None = None) -> dict:
    det = clean(load_raw(raw_dir))
    det.write_parquet(DET_PATH)
    build_fine(det).write_parquet(FINE_PATH)
    mt = build_model_table(det)
    mt.write_parquet(MODEL_PATH)
    cov = sensor_coverage(det)
    log.info("coverage:\n%s", cov)
    return {"detections": det.height, "model_rows": mt.height,
            "coverage": cov.with_columns(pl.col("first").cast(pl.Utf8),
                                         pl.col("last").cast(pl.Utf8)).to_dicts()}


def load_detections(columns: list[str] | None = None) -> pl.DataFrame:
    return pl.read_parquet(DET_PATH, columns=columns)


def load_model_table() -> pl.DataFrame:
    return pl.read_parquet(MODEL_PATH)


def load_fine() -> pl.DataFrame:
    return pl.read_parquet(FINE_PATH)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())
