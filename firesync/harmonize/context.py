"""Loads every input of the harmonisation once and prepares the model table."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import polars as pl

from .. import config, processing
from ..ingest import burned_area, landcover
from ..seasonal import detect_start_week
from . import availability, pairing
from .models import prepare

log = logging.getLogger(__name__)
PAIRED = config.PROCESSED / "paired_week.parquet"
AVAIL = config.PROCESSED / "availability_week.parquet"
AVAIL_DAY = config.PROCESSED / "availability_day.parquet"


@dataclass
class Context:
    det: pl.DataFrame
    d: pl.DataFrame            # prepared res-5 cell-week table
    week_av: pl.DataFrame
    start_week: int
    lc_meta: dict
    burned: pl.DataFrame | None
    paired: pl.DataFrame


def region_start_week(mt: pl.DataFrame) -> int:
    clim = (mt.filter(pl.col("year") >= 2012).group_by("week")
            .agg(pl.col("n_VIIRS_SNPP").sum()).sort("week")["n_VIIRS_SNPP"].to_numpy())
    if clim.sum() == 0:
        clim = (mt.group_by("week").agg((pl.col("n_MODIS_T") + pl.col("n_MODIS_A")).sum())
                .sort("week").to_series(1).to_numpy())
    return detect_start_week(clim)


def build(rebuild_pairs: bool = False) -> Context:
    det = processing.load_detections()
    mt = processing.load_model_table()
    day_av = availability.daily(det)
    week_av = availability.weekly(day_av)
    day_av.write_parquet(AVAIL_DAY)
    week_av.write_parquet(AVAIL)
    if rebuild_pairs or not PAIRED.exists():
        log.info("pairing overpasses ...")
        paired = pairing.build(det)
        paired.write_parquet(PAIRED)
    else:
        paired = pl.read_parquet(PAIRED)
    lc = landcover.load()
    sw = region_start_week(mt)
    d = prepare(mt, week_av, lc, paired, sw)
    log.info("context: %d rows, start week %d, land cover=%s", d.height, sw,
             landcover.meta().get("source"))
    return Context(det=det, d=d, week_av=week_av, start_week=sw, lc_meta=landcover.meta(),
                   burned=burned_area.load(), paired=paired)
