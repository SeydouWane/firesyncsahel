"""Near-simultaneous overpass pairing.

Aqua MODIS and S-NPP VIIRS both cross the equator around 13:30 / 01:30 local
time, and NOAA-20 / NOAA-21 fly ~25-50 min ahead of S-NPP on the same orbit.
Pairing their passes compares *the same fires at the same moment*, which
isolates the sensor sensitivity difference from the diurnal fire cycle.

Algorithm
1. Detections of each sensor are grouped into passes (time gap > 20 min).
2. Each pass of the "source" sensor is matched to the nearest reference pass
   within ``tolerance`` minutes.
3. Swath edges differ between instruments, so a cell only counts as
   co-observed when both sensors have at least one detection in its H3 res-3
   neighbourhood (~12 000 km²) during the matched pass.
4. Matched counts are summed per (H3 res-5 cell, year, week).
"""
from __future__ import annotations

import polars as pl

from ..config import MODEL

PAIRS = {"A_SNPP": ("MODIS_A", "VIIRS_SNPP"),
         "N20_SNPP": ("VIIRS_N20", "VIIRS_SNPP"),
         "N21_SNPP": ("VIIRS_N21", "VIIRS_SNPP")}


def _passes(det: pl.DataFrame, sensor: str, gap: int = 20) -> pl.DataFrame:
    d = (det.filter(pl.col("sensor") == sensor)
         .with_columns((pl.col("date").cast(pl.Int32).cast(pl.Int64) * 1440
                        + pl.col("utc_min")).alias("ts"))
         .sort("ts"))
    if d.height == 0:
        return d.with_columns(pl.lit(0).alias("pass_id"))
    d = d.with_columns((pl.col("ts").diff().fill_null(gap + 1) > gap).cum_sum().alias("pass_id"))
    return d


def matched_counts(det: pl.DataFrame, pair: str,
                   tolerance: int = MODEL.overpass_tolerance_min) -> pl.DataFrame:
    src, ref = PAIRS[pair]
    ds, dr = _passes(det, src), _passes(det, ref)
    if ds.height == 0 or dr.height == 0:
        return pl.DataFrame(schema={"h3_5": pl.Int64, "year": pl.Int16, "week": pl.Int8,
                                    "n_src": pl.Int64, "n_ref": pl.Int64, "pair": pl.Utf8})
    ps = ds.group_by("pass_id").agg(pl.col("ts").median().alias("t")).sort("t")
    pr = dr.group_by("pass_id").agg(pl.col("ts").median().alias("t")).sort("t")
    m = ps.join_asof(pr.rename({"pass_id": "ref_pass"}), on="t", strategy="nearest",
                     tolerance=float(tolerance)).drop_nulls("ref_pass")
    m = m.select(pl.col("pass_id").alias("src_pass"), "ref_pass")
    cs = (ds.join(m, left_on="pass_id", right_on="src_pass")
          .group_by(["ref_pass", "h3_3", "h3_5", "year", "week"]).len("n_src"))
    cr = (dr.join(m.select("ref_pass").unique(), left_on="pass_id", right_on="ref_pass")
          .rename({"pass_id": "ref_pass"})
          .group_by(["ref_pass", "h3_3", "h3_5", "year", "week"]).len("n_ref"))
    both3 = (cs.group_by(["ref_pass", "h3_3"]).agg(pl.col("n_src").sum().alias("s3"))
             .join(cr.group_by(["ref_pass", "h3_3"]).agg(pl.col("n_ref").sum().alias("r3")),
                   on=["ref_pass", "h3_3"])
             .select("ref_pass", "h3_3"))
    keys = ["ref_pass", "h3_3", "h3_5", "year", "week"]
    j = (cs.join(both3, on=["ref_pass", "h3_3"])
         .join(cr.join(both3, on=["ref_pass", "h3_3"]), on=keys, how="full", coalesce=True)
         .fill_null(0))
    return (j.group_by(["h3_5", "year", "week"])
            .agg(pl.col("n_src").sum().cast(pl.Int64), pl.col("n_ref").sum().cast(pl.Int64))
            .with_columns(pl.lit(pair).alias("pair")))


def build(det: pl.DataFrame) -> pl.DataFrame:
    need = det.select("sensor", "date", "utc_min", "h3_3", "h3_5", "year", "week")
    frames = [matched_counts(need, p) for p in PAIRS]
    return pl.concat([f for f in frames if f.height], how="vertical_relaxed")
