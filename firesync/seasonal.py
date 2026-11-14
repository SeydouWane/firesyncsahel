"""Fire-year calendar helpers.

In the Sahel the dry season straddles two calendar years (October -> May), so
calendars are organised by *fire year*: 52 weeks starting at the week of
climatological minimum activity. The calendar week index is
``min((day_of_year - 1) // 7, 51)``; the start week is a value in 0..51.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl

from .config import WEEKS_PER_YEAR

W = WEEKS_PER_YEAR


def add_fire_year(df: pl.DataFrame, start_week: int) -> pl.DataFrame:
    return df.with_columns(
        pl.when(pl.col("week") >= start_week).then(pl.col("year"))
        .otherwise(pl.col("year") - 1).cast(pl.Int16).alias("fyear"),
        ((pl.col("week").cast(pl.Int16) - start_week) % W).cast(pl.Int8).alias("fweek"),
    )


def detect_start_week(weekly_clim: np.ndarray, smooth: int = 5) -> int:
    """Week of minimum (circularly smoothed) climatological activity."""
    x = np.asarray(weekly_clim, dtype=float)
    if not np.isfinite(x).any() or np.nansum(x) <= 0:
        return 30  # late July: a sensible default for the northern tropics
    x = np.nan_to_num(x)
    k = np.ones(smooth) / smooth
    ext = np.concatenate([x[-smooth:], x, x[:smooth]])
    sm = np.convolve(ext, k, mode="same")[smooth:-smooth]
    return int(np.argmin(sm))


def week_start_date(year: int, week: int) -> date:
    return date(year, 1, 1) + timedelta(days=7 * int(week))


def fire_week_start(fyear: int, fweek: int, start_week: int) -> date:
    w = (start_week + fweek) % W
    y = fyear + (1 if start_week + fweek >= W else 0)
    return week_start_date(y, w)


def fire_year_label(fy: int, start_week: int) -> str:
    return str(fy) if start_week == 0 else f"{fy}-{str(fy + 1)[-2:]}"
