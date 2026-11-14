"""Which sensor actually observed the region on a given day / week.

Detection files only list fires, not overpasses, so an outage (safe mode,
end of mission, missing granules) has to be inferred: a sensor is considered
*missing* on a day when it reports no detection over the whole region while
the other sensors together report at least ``min_other`` detections. Outside
its record (before launch, after the end of distribution) a sensor is missing
by definition. The weekly availability is the fraction of available days.
"""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from ..config import SENSORS, WEEKS_PER_YEAR
from ..processing import SENSOR_ORDER


def daily(det: pl.DataFrame, min_other: int = 15) -> pl.DataFrame:
    counts = det.group_by(["date", "sensor"]).len().pivot(on="sensor", index="date",
                                                          values="len").fill_null(0)
    for s in SENSOR_ORDER:
        if s not in counts.columns:
            counts = counts.with_columns(pl.lit(0, pl.UInt32).alias(s))
    first_day = det["date"].min()
    last_day = det["date"].max()
    days = pl.DataFrame({"date": pl.date_range(first_day, last_day, "1d", eager=True)})
    counts = days.join(counts, on="date", how="left").fill_null(0)
    last_by = det.group_by("sensor").agg(pl.col("date").min().alias("f"),
                                         pl.col("date").max().alias("l"))
    rng = {r["sensor"]: (r["f"], r["l"]) for r in last_by.to_dicts()}
    exprs = []
    for s in SENSOR_ORDER:
        meta = SENSORS[s]
        f, l = rng.get(s, (None, None))
        first = max(date.fromisoformat(meta.first), f) if f else None
        last = l
        if meta.last:
            last = min(l, date.fromisoformat(meta.last) - timedelta(days=1)) if l else None
        others = sum(pl.col(o).cast(pl.Int64) for o in SENSOR_ORDER if o != s)
        if first is None:
            exprs.append(pl.lit(False).alias(f"ok_{s}"))
            continue
        in_record = (pl.col("date") >= first) & (pl.col("date") <= last)
        outage = (pl.col(s) == 0) & (others >= min_other)
        exprs.append((in_record & ~outage).alias(f"ok_{s}"))
    return counts.with_columns(exprs)


def weekly(day_av: pl.DataFrame) -> pl.DataFrame:
    """Fraction of the week's days observed by each sensor.

    Divided by the true length of the week (7, or 8-9 for week 51) so that the
    last, still running week of the record counts as partial, not complete.
    """
    from ..processing import week_days
    d = day_av.with_columns(
        pl.col("date").dt.year().cast(pl.Int16).alias("year"),
        ((pl.col("date").dt.ordinal_day() - 1) // 7).clip(0, WEEKS_PER_YEAR - 1)
        .cast(pl.Int8).alias("week"))
    w = (d.group_by(["year", "week"])
         .agg([pl.col(f"ok_{s}").sum().alias(f"n_{s}") for s in SENSOR_ORDER])
         .sort(["year", "week"]))
    nd = pl.Series([week_days(y, wk) for y, wk in zip(w["year"].to_list(), w["week"].to_list())])
    return w.with_columns(pl.Series("_nd", nd)).select(
        "year", "week", *[(pl.col(f"n_{s}") / pl.col("_nd")).alias(f"f_{s}") for s in SENSOR_ORDER])
