"""Fit the final models and write the serving tables.

Outputs (data/models):
  harm_5.parquet      model cell-weeks without valid S-NPP observation:
                      source + B ensemble members (S-NPP-equivalent counts)
  share_7.parquet     share of each res-7 cell in its res-5 parent (VIIRS
                      climatology, Laplace-smoothed) to allocate background
  viirs_ratio.parquet NOAA-20 / NOAA-21 -> S-NPP ratios per (cell, season bin)
  hex_year.parquet    harmonised annual totals per res-5 cell and fire year
  meta.json           theta / kappa per source, start week, training years...
  step_test.json      independent MCD64A1 continuity test across 2012
"""
from __future__ import annotations

import json
import logging
import time

import numpy as np
import polars as pl

from .. import config, processing
from ..config import GRID, MODEL
from ..grid import parents
from . import validate
from .context import Context
from .models import GBMEnsemble, ViirsRatio, usable

log = logging.getLogger(__name__)
OUT = config.MODELS
SOURCES = {
    "VIIRS_SNPP": {"fr": "VIIRS S-NPP (observé)", "en": "VIIRS S-NPP (observed)"},
    "N20": {"fr": "VIIRS NOAA-20 → S-NPP", "en": "VIIRS NOAA-20 → S-NPP"},
    "N21": {"fr": "VIIRS NOAA-21 → S-NPP", "en": "VIIRS NOAA-21 → S-NPP"},
    "TA": {"fr": "MODIS Terra+Aqua → S-NPP", "en": "MODIS Terra+Aqua → S-NPP"},
    "T": {"fr": "MODIS Terra → S-NPP", "en": "MODIS Terra → S-NPP"},
    "A": {"fr": "MODIS Aqua → S-NPP", "en": "MODIS Aqua → S-NPP"},
}


def _source_expr() -> pl.Expr:
    return (pl.when(pl.col("V").is_not_null()).then(pl.lit("VIIRS_SNPP"))
            .when(pl.col("N20").is_not_null()).then(pl.lit("N20"))
            .when(pl.col("N21").is_not_null()).then(pl.lit("N21"))
            .when(pl.col("T").is_not_null() & pl.col("A").is_not_null()).then(pl.lit("TA"))
            .when(pl.col("T").is_not_null()).then(pl.lit("T"))
            .when(pl.col("A").is_not_null()).then(pl.lit("A"))
            .otherwise(pl.lit(None)))


def share_table() -> pl.DataFrame:
    fine = processing.load_fine().filter(pl.col("sensor") == "VIIRS_SNPP")
    c7 = fine.group_by("h3_7").agg(pl.col("n").sum())
    c7 = c7.with_columns(pl.Series("h3_5", parents(c7["h3_7"].to_numpy(), GRID.model_res)))
    tot = c7.group_by("h3_5").agg(pl.col("n").sum().alias("tot"))
    # Laplace smoothing over the 49 children of a res-5 cell (7^2)
    return (c7.join(tot, on="h3_5")
            .with_columns(((pl.col("n") + 0.5) / (pl.col("tot") + 0.5 * 49)).alias("share"))
            .select("h3_7", "h3_5", "share", "tot"))


def fit_and_write(ctx: Context, report: dict | None = None) -> dict:
    t0 = time.time()
    report = report or validate.load_report()
    if report is None:
        raise RuntimeError("run validation first (python -m firesync validate)")
    d = ctx.d.with_columns(_source_expr().alias("source"))
    train = report["train_fire_years"]
    B = MODEL.n_bootstrap
    meta = {"start_week": ctx.start_week, "train_fire_years": train, "members": B,
            "reference": config.REFERENCE_SENSOR, "sources": SOURCES, "theta": {}, "kappa": {},
            "land_cover": ctx.lc_meta, "generated": time.strftime("%Y-%m-%d %H:%M")}
    frames = []
    for variant in ("TA", "T", "A"):
        sub = d.filter(pl.col("source") == variant)
        vrep = report["variants"].get(variant if variant != "A" else "T", {}).get("gbm", {})
        meta["theta"][variant] = vrep.get("theta") or 5.0
        meta["kappa"][variant] = vrep.get("kappa") or 1.5
        if sub.height == 0:
            continue
        log.info("final GBM %s on %d rows -> predict %d", variant, len(train), sub.height)
        m = GBMEnsemble(variant, n_members=B).fit(d, train)
        mem = m.predict_members(sub)
        frames.append(sub.select("h3_5", "year", "week", "source").with_columns(
            [pl.Series(f"m{b}", mem[:, b]) for b in range(B)]))
    harm = pl.concat(frames).with_columns(
        pl.mean_horizontal([f"m{b}" for b in range(B)]).alias("mu"))
    harm.write_parquet(OUT / "harm_5.parquet")

    vc = report.get("viirs_continuity") or {}
    vc21 = report.get("viirs_continuity_n21") or vc
    meta["theta"]["N20"], meta["kappa"]["N20"] = vc.get("theta") or 20.0, vc.get("kappa") or 1.5
    meta["theta"]["N21"], meta["kappa"]["N21"] = vc21.get("theta") or 20.0, vc21.get("kappa") or 1.5
    allw = write_serving(ctx, d, harm, meta)
    meta["step_test"] = step_test(ctx, d, harm, allw)
    meta["seconds"] = round(time.time() - t0, 1)
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2, default=float))
    log.info("serving tables written in %.0fs", time.time() - t0)
    return meta


def viirs_ratios(d: pl.DataFrame, meta: dict) -> pl.DataFrame | None:
    """NOAA-20 / NOAA-21 -> S-NPP ratios per (cell, season bin), written to disk."""
    ratios = []
    for src in ("N20", "N21"):
        vr = ViirsRatio(src).fit(d)
        if getattr(vr, "ok", False):
            ratios.append(vr.tab.with_columns(pl.lit(src).alias("src")))
            meta.setdefault("viirs_global", {})[src] = vr.r_glob
            meta.setdefault("viirs_season", {})[src] = vr.s.to_dicts()
            meta.setdefault("viirs_train_rows", {})[src] = vr.n_train
    if not ratios:
        return None
    rt = pl.concat(ratios)
    rt.write_parquet(OUT / "viirs_ratio.parquet")
    return rt


def cell_weeks(d: pl.DataFrame, harm: pl.DataFrame, ratios: pl.DataFrame | None, meta: dict,
               start_week: int) -> pl.DataFrame:
    """Harmonised weekly value H per model cell: observed S-NPP, converted
    NOAA-20/21, or MODIS-model mean, whichever is the week's source."""
    obs = d.filter(pl.col("source") == "VIIRS_SNPP").select("h3_5", "year", "week", pl.col("V").alias("H"),
                                                           pl.lit("VIIRS_SNPP").alias("src"))
    nv = d.filter(pl.col("source").is_in(["N20", "N21"]))
    if nv.height and ratios is not None:
        g = meta.get("viirs_global", {})
        nv = (nv.join(ratios, left_on=["h3_5", "sbin", "source"], right_on=["h3_5", "sbin", "src"], how="left")
              .with_columns(pl.col("r").fill_null(
                  pl.when(pl.col("source") == "N21").then(g.get("N21", g.get("N20", 1.0))).otherwise(g.get("N20", 1.0))))
              .select("h3_5", "year", "week",
                      (pl.when(pl.col("source") == "N20").then(pl.col("N20")).otherwise(pl.col("N21"))
                       * pl.col("r")).alias("H"), pl.col("source").alias("src")))
    else:
        nv = obs.head(0)
    srcs = d.select("h3_5", "year", "week", pl.col("source").alias("cur"))
    mod = (harm.join(srcs, on=["h3_5", "year", "week"])
           .filter(pl.col("cur") == pl.col("source"))  # only weeks still without VIIRS
           .select("h3_5", "year", "week", pl.col("mu").alias("H"), pl.col("source").alias("src")))
    from ..seasonal import add_fire_year
    allw = pl.concat([obs, nv.cast(obs.schema), mod.cast(obs.schema)])
    return add_fire_year(allw, start_week).sort(["h3_5", "year", "week"])


def write_serving(ctx: Context, d: pl.DataFrame, harm: pl.DataFrame, meta: dict) -> pl.DataFrame:
    ratios = viirs_ratios(d, meta)
    share_table().write_parquet(OUT / "share_7.parquet")
    # the fire-year start of the model in service stays fixed between refreshes
    # (new weeks of data can move the detected minimum by a week)
    allw = cell_weeks(d, harm, ratios, meta, int(meta.get("start_week", ctx.start_week)))
    allw.write_parquet(OUT / "cell_week.parquet")
    hy = allw.group_by(["h3_5", "fyear"]).agg(pl.col("H").sum()).sort(["h3_5", "fyear"])
    hy.write_parquet(OUT / "hex_year.parquet")
    meta["fire_years"] = sorted(hy["fyear"].unique().to_list())
    meta["data_version"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return allw


def refresh(ctx: Context) -> dict:
    """Integrate new detections (NRT, NOAA-21…) without refitting the MODIS model."""
    t0 = time.time()
    meta = json.loads((OUT / "meta.json").read_text())
    d = ctx.d.with_columns(_source_expr().alias("source"))
    harm = pl.read_parquet(OUT / "harm_5.parquet")
    write_serving(ctx, d, harm, meta)
    meta["refreshed"] = time.strftime("%Y-%m-%d %H:%M")
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2, default=float))
    log.info("serving tables refreshed in %.0fs", time.time() - t0)
    return {"seconds": round(time.time() - t0, 1), "fire_years": meta["fire_years"][-3:]}


def step_test(ctx: Context, d: pl.DataFrame, harm: pl.DataFrame, allw: pl.DataFrame) -> dict:
    """Independent continuity test against MCD64A1 burned area.

    MCD64A1 does not change sensor in 2012. If the harmonised active-fire
    series is continuous, the ratio detections / burned km² must not jump
    between 2007-2011 and 2012-2016; the naive splice jumps by ~VIIRS/MODIS.
    """
    if ctx.burned is None:
        return {"available": False}
    from ..seasonal import add_fire_year
    cells =d.select("h3_5", "h3_3").unique()
    b = add_fire_year(ctx.burned.join(cells, on="h3_5"), ctx.start_week)
    bz = b.group_by(["fyear"]).agg(pl.col("ba_km2").sum())
    h = allw.group_by("fyear").agg(pl.col("H").sum())
    naive = add_fire_year(
        d.select("h3_5", "year", "week",
                 pl.when(pl.col("V").is_not_null()).then(pl.col("V"))
                 .otherwise(pl.col("T").fill_null(0) + pl.col("A").fill_null(0)).alias("N")),
        ctx.start_week).group_by("fyear").agg(pl.col("N").sum())
    j = bz.join(h, on="fyear").join(naive, on="fyear").sort("fyear")
    j = j.filter((pl.col("fyear") >= 2001) & (pl.col("fyear") <= 2024))
    j = j.with_columns((pl.col("H") / pl.col("ba_km2")).alias("r_harm"),
                       (pl.col("N") / pl.col("ba_km2")).alias("r_naive"))

    def step(col):
        pre = j.filter(pl.col("fyear").is_between(2007, 2011))[col].log().mean()
        post = j.filter(pl.col("fyear").is_between(2012, 2016))[col].log().mean()
        return float(np.exp(post - pre))

    # per-zone steps (res-3) for robustness
    bzz = b.group_by(["h3_3", "fyear"]).agg(pl.col("ba_km2").sum())
    hz = allw.join(cells, on="h3_5").group_by(["h3_3", "fyear"]).agg(pl.col("H").sum())
    nz = add_fire_year(d.select("h3_3", "year", "week",
                                pl.when(pl.col("V").is_not_null()).then(pl.col("V"))
                                .otherwise(pl.col("T").fill_null(0) + pl.col("A").fill_null(0))
                                .alias("N")), ctx.start_week) \
        .group_by(["h3_3", "fyear"]).agg(pl.col("N").sum())
    z = bzz.join(hz, on=["h3_3", "fyear"]).join(nz, on=["h3_3", "fyear"])
    z = z.filter(pl.col("ba_km2") > 20)
    zs = []
    for _, g in z.group_by("h3_3"):
        pre = g.filter(pl.col("fyear").is_between(2007, 2011))
        post = g.filter(pl.col("fyear").is_between(2012, 2016))
        if pre.height >= 3 and post.height >= 3:
            zs.append({
                "harm": float(np.exp((post["H"] / post["ba_km2"]).log().mean()
                                     - (pre["H"] / pre["ba_km2"]).log().mean())),
                "naive": float(np.exp((post["N"] / post["ba_km2"]).log().mean()
                                      - (pre["N"] / pre["ba_km2"]).log().mean()))})
    corr = float(np.corrcoef(np.log(j["H"].to_numpy()), np.log(j["ba_km2"].to_numpy()))[0, 1])
    return {"available": True, "step_harmonised": step("r_harm"), "step_naive": step("r_naive"),
            "zones": len(zs),
            "zone_step_harmonised_median": float(np.median([s["harm"] for s in zs])) if zs else None,
            "zone_step_naive_median": float(np.median([s["naive"] for s in zs])) if zs else None,
            "corr_log_annual_harm_vs_ba": corr,
            "annual": j.select("fyear", "ba_km2", "H", "N").to_dicts()}
