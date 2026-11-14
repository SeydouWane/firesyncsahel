"""Transparent validation of the harmonisation.

1. Leave-one-fire-year-out over the overlap (train) years: each year is
   removed from training, then predicted from MODIS only and compared to the
   observed VIIRS S-NPP series. Four models are compared: naive splice, single
   ratio, stratified empirical-Bayes ratio and the gradient-boosting ensemble.
2. Metrics at five scales (cell-week, zone-week, region-week, zone-year,
   region-year) + errors on season onset / peak / end.
3. Calibration of the uncertainty (kappa) and empirical coverage of 90 %
   intervals for the probabilistic models.
4. Out-of-window test on later years (Terra / Aqua orbital drift period).
5. VIIRS NOAA-20 -> S-NPP continuity (needed after S-NPP ends, 2026-11-01).
6. Overpass-pairing diagnostic (instantaneous vs weekly ratio).
"""
from __future__ import annotations

import json
import logging
import time

import numpy as np
import polars as pl

from .. import config
from ..config import MODEL, SEASON
from ..indicators import season_dates
from . import uncertainty as unc
from .context import Context
from .models import (GBMEnsemble, Naive, SingleRatio, StratifiedEB, ViirsRatio, m_expr,
                     usable)

log = logging.getLogger(__name__)
REPORT = config.VALIDATION / "report.json"
SCALES = {
    "cell_year": ["h3_5", "fyear"],
    "cell_week": ["h3_5", "fyear", "fweek"],
    "zone_week": ["h3_3", "fyear", "fweek"],
    "region_week": ["fyear", "fweek"],
    "zone_year": ["h3_3", "fyear"],
    "region_year": ["fyear"],
}
CAL_SCALE = "zone_week"


def _gkey(df: pl.DataFrame, cols: list[str]) -> np.ndarray:
    return df.select(pl.struct(cols).hash(seed=1)).to_series().to_numpy()


def point_metrics(obs: np.ndarray, pred: np.ndarray) -> dict:
    obs, pred = np.asarray(obs, float), np.asarray(pred, float)
    s = obs.sum()
    lo, lp = np.log1p(obs), np.log1p(pred)
    r = float(np.corrcoef(lo, lp)[0, 1]) if obs.std() > 0 and pred.std() > 0 else None
    return {"n": int(len(obs)), "obs_total": float(s),
            "bias_pct": float(100 * (pred.sum() - s) / s) if s else None,
            "nmae_pct": float(100 * np.abs(pred - obs).sum() / s) if s else None,
            "rmse_log": float(np.sqrt(np.mean((lp - lo) ** 2))),
            "r_log": r}


def _predict_oof(ctx: Context, model_cls, variant: str, years, **kw):
    """Leave-one-fire-year-out predictions on usable rows of `years`."""
    d = ctx.d
    rows, mem = [], []
    for y in years:
        train = [t for t in years if t != y]
        m = model_cls(variant, **kw).fit(d, train)
        te = d.filter(usable(d, variant, True) & (pl.col("fyear") == y))
        rows.append(te.select("h3_5", "h3_3", "fyear", "fweek", "V", m_expr(variant).alias("M")))
        mem.append(m.predict_members(te))
    return pl.concat(rows), np.vstack(mem)


def _predict_test(ctx: Context, model_cls, variant: str, train, test, **kw):
    d = ctx.d
    m = model_cls(variant, **kw).fit(d, train)
    te = d.filter(usable(d, variant, True) & pl.col("fyear").is_in(list(test)))
    return (te.select("h3_5", "h3_3", "fyear", "fweek", "V", m_expr(variant).alias("M")),
            m.predict_members(te))


def _active(rows: pl.DataFrame, g: np.ndarray, obs: np.ndarray) -> np.ndarray:
    """Model-independent evaluation subset: groups with a VIIRS or a source detection."""
    _, msum, _, _ = unc.group_sums(g, rows["M"].to_numpy()[:, None], None, 1e6)
    return (obs > 0) | (msum > 0)


def evaluate(rows: pl.DataFrame, members: np.ndarray, theta: float | None,
             kappa: float | None, prob: bool) -> dict:
    out = {}
    obs_all = rows["V"].to_numpy()
    for scale, cols in SCALES.items():
        g = _gkey(rows, cols)
        uniq, mean, vn, vm = unc.group_sums(g, members, None, theta or 1e6)
        _, obs, _, _ = unc.group_sums(g, obs_all[:, None], None, 1e6)
        act = _active(rows, g, obs)
        res = point_metrics(obs[act], mean[act])
        if prob and kappa is not None:
            lo, hi = unc.interval(mean[act], (vn + vm)[act], kappa, MODEL.interval)
            res["coverage90"] = float(np.mean((obs[act] >= lo) & (obs[act] <= hi)))
            res["rel_width"] = float(np.sum(hi - lo) / max(np.sum(obs[act]), 1))
        out[scale] = res
    return out


def season_errors(rows: pl.DataFrame, members: np.ndarray, min_total: float = 300) -> dict:
    """Mean absolute error (weeks) of onset / peak / end at zone and region level."""
    mu = members.mean(axis=1)
    df = rows.with_columns(pl.Series("P", mu))
    out = {}
    for name, keys in (("zone", ["h3_3", "fyear"]), ("region", ["fyear"])):
        agg = (df.group_by(keys + ["fweek"]).agg(pl.col("V").sum(), pl.col("P").sum())
               .sort(keys + ["fweek"]))
        errs = {"onset": [], "peak": [], "end": [], "duration": []}
        for _, g in agg.group_by(keys):
            o = np.zeros(52); p = np.zeros(52)
            o[g["fweek"].to_numpy()] = g["V"].to_numpy()
            p[g["fweek"].to_numpy()] = g["P"].to_numpy()
            if o.sum() < (min_total if name == "zone" else 1000):
                continue
            so, sp = season_dates(o), season_dates(p)
            for k in errs:
                errs[k].append(abs(sp[k] - so[k]))
        out[name] = {k: (float(np.mean(v)) if v else None) for k, v in errs.items()}
        out[name]["n"] = len(errs["onset"])
    return out


def drift_diagnostic(ctx: Context) -> list[dict]:
    d = ctx.d.filter(pl.col("V").is_not_null())
    a = (d.group_by("fyear").agg(pl.col("V").sum(), pl.col("T").sum(), pl.col("A").sum(),
                                 pl.col("N20").sum())
         .sort("fyear")
         .with_columns((pl.col("V") / pl.col("T")).alias("V_T"),
                       (pl.col("V") / pl.col("A")).alias("V_A"),
                       (pl.col("V") / (pl.col("T") + pl.col("A"))).alias("V_TA"),
                       pl.when(pl.col("N20") > 0).then(pl.col("V") / pl.col("N20")).alias("V_N20")))
    return a.to_dicts()


def pairing_diagnostic(ctx: Context) -> dict:
    p = ctx.paired.filter(pl.col("pair") == "A_SNPP")
    if p.height == 0:
        return {}
    from ..ingest.landcover import GROUPS
    j = p.join(ctx.d.select("h3_5", "lc_major").unique(), on="h3_5", how="left")
    by_lc = (j.group_by("lc_major").agg(pl.col("n_ref").sum(), pl.col("n_src").sum())
             .with_columns((pl.col("n_ref") / pl.col("n_src")).alias("ratio")).sort("lc_major"))
    by_s = (j.with_columns((pl.col("week") // 4).alias("sbin")).group_by("sbin")
            .agg(pl.col("n_ref").sum(), pl.col("n_src").sum())
            .with_columns((pl.col("n_ref") / pl.col("n_src")).alias("ratio")).sort("sbin"))
    w = ctx.d.filter(pl.col("V").is_not_null() & pl.col("A").is_not_null())
    weekly = float(w["V"].sum() / max(w["A"].sum(), 1))
    inst = float(p["n_ref"].sum() / max(p["n_src"].sum(), 1))
    return {"instantaneous_ratio": inst, "weekly_ratio_V_over_A": weekly,
            "matched_aqua_detections": int(p["n_src"].sum()),
            "by_landcover": [{"group": GROUPS[int(r["lc_major"])] if r["lc_major"] is not None else None,
                              "ratio": r["ratio"], "n": r["n_src"]} for r in by_lc.to_dicts()],
            "by_season_bin": by_s.select("sbin", "ratio", pl.col("n_src").alias("n")).to_dicts()}


def viirs_continuity(ctx: Context, src: str = "N20") -> dict:
    """Leave-one-fire-year-out of the NOAA-20 (or NOAA-21) -> S-NPP ratio model
    over the overlap with S-NPP. For NOAA-21 (overlap from 2023 only) folds are
    half fire years so that at least 4 folds exist."""
    d = ctx.d.filter(pl.col(src).is_not_null() & pl.col("V").is_not_null())
    if d.height == 0:
        return {}
    if src == "N21":
        d = d.with_columns((pl.col("fyear") * 2 + (pl.col("fweek") >= 26).cast(pl.Int16)).alias("fold"))
    else:
        d = d.with_columns(pl.col("fyear").cast(pl.Int32).alias("fold"))
    years = sorted(d["fold"].unique().to_list())
    if src == "N20":
        years = [y for y in years if 2018 <= y <= 2024]
    if len(years) < 3:
        return {}
    rows, mus, sds = [], [], []
    for y in years:
        dtr = d.filter(pl.col("fold") != y)
        m = ViirsRatio(src).fit(dtr)
        te = d.filter(pl.col("fold") == y)
        r, rsd = m.ratios(te)
        n = te[src].to_numpy()
        rows.append(te.select("h3_5", "h3_3", "fyear", "fweek", "V", pl.col(src).alias("M")))
        mus.append(n * r); sds.append(n * rsd)
    rows = pl.concat(rows)
    mu = np.concatenate(mus); sd = np.concatenate(sds)
    obs = rows["V"].to_numpy()
    theta = unc.nb_theta(obs, mu)
    # members from +/- 1 sd comonotone perturbation (2-point ensemble)
    members = np.maximum(np.column_stack([mu - sd, mu + sd]), 0)
    g = _gkey(rows, SCALES[CAL_SCALE])
    _, mean, vn, vm = unc.group_sums(g, members, None, theta)
    _, o, _, _ = unc.group_sums(g, obs[:, None], None, 1e6)
    act = _active(rows, g, o)
    kappa = unc.calibrate_kappa(o[act], mean[act], (vn + vm)[act], hi=12.0)
    res = evaluate(rows, members, theta, kappa, True)
    naive = evaluate(rows, rows["M"].to_numpy()[:, None].astype(float), None, None, False)
    ks = kappa_by_scale(rows, members, theta)
    return {"src": src, "years": years, "theta": theta, "kappa": kappa, "metrics": res, "kappa_scale": ks,
            "scaled_coverage": {k: _cov_scaled(rows, members, theta, ks, k) for k in SCALES},
            "naive_metrics": naive, "rows": int(d.height),
            "period": [str(d["year"].min()), str(d["year"].max())],
            "global_ratio": float(d["V"].sum() / d[src].sum())}


def run(ctx: Context, quick: bool = False, train_years=None, test_years=None) -> dict:
    t0 = time.time()
    train = [y for y in (train_years or MODEL.train_fire_years)
             if ctx.d.filter((pl.col("fyear") == y) & pl.col("V").is_not_null()).height]
    test = list(test_years if test_years is not None else MODEL.test_fire_years)
    nb = 4 if not quick else 2
    specs = [("naive", Naive, {}), ("single_ratio", SingleRatio, {}),
             ("stratified_eb", StratifiedEB, {"n_draws": 16}),
             ("gbm", GBMEnsemble, {"n_members": nb})]
    report = {"generated": time.strftime("%Y-%m-%d %H:%M"), "train_fire_years": train,
              "test_fire_years": test, "start_week": ctx.start_week,
              "land_cover": ctx.lc_meta, "interval": MODEL.interval,
              "calibration_scale": CAL_SCALE, "variants": {}}
    for variant in ("TA", "T"):
        vr = {}
        for name, cls, kw in specs:
            log.info("LOYO %s/%s ...", variant, name)
            rows, mem = _predict_oof(ctx, cls, variant, train, **kw)
            _save_pred(rows, mem, f"oof_{variant}_{name}")
            trow = tmem = None
            if variant == "TA" and test:
                trow, tmem = _predict_test(ctx, cls, variant, train, test, **kw)
                _save_pred(trow, tmem, f"test_{variant}_{name}")
            res = score(rows, mem, trow, tmem, prob=name in ("stratified_eb", "gbm"))
            vr[name] = res
            log.info("  %s/%s region_year bias=%.1f%%  zone_week nmae=%.1f%%  (%.0fs)",
                     variant, name, res["loyo"]["region_year"]["bias_pct"] or 0,
                     res["loyo"]["zone_week"]["nmae_pct"] or 0, time.time() - t0)
        report["variants"][variant] = vr
    report["drift"] = drift_diagnostic(ctx)
    report["pairing"] = pairing_diagnostic(ctx)
    report["viirs_continuity"] = viirs_continuity(ctx, "N20")
    report["viirs_continuity_n21"] = viirs_continuity(ctx, "N21")
    report["models"] = {n: c.label for n, c, _ in specs}
    report["seconds"] = round(time.time() - t0, 1)
    REPORT.write_text(json.dumps(report, indent=2, default=float))
    return report


def load_report() -> dict | None:
    return json.loads(REPORT.read_text()) if REPORT.exists() else None


# ------------------------------------------------------------------ caching
def _save_pred(rows: pl.DataFrame, mem: np.ndarray, name: str) -> None:
    if rows is None or rows.height == 0:
        return
    rows.with_columns([pl.Series(f"m{b}", mem[:, b].astype(np.float32)) for b in range(mem.shape[1])]) \
        .write_parquet(config.VALIDATION / f"{name}.parquet")


def _load_pred(name: str):
    p = config.VALIDATION / f"{name}.parquet"
    if not p.exists():
        return None, None
    df = pl.read_parquet(p)
    mcols = [c for c in df.columns if c.startswith("m") and c[1:].isdigit()]
    return df.drop(mcols), df.select(mcols).to_numpy().astype(np.float64)


def score(rows, mem, trow=None, tmem=None, prob: bool = False) -> dict:
    """Metrics, NB dispersion and calibrated kappa from out-of-sample predictions."""
    theta = kappa = raw = None
    if prob:
        theta = unc.nb_theta(rows["V"].to_numpy(), mem.mean(axis=1))
        g = _gkey(rows, SCALES[CAL_SCALE])
        _, mean, vn, vm = unc.group_sums(g, mem, None, theta)
        _, o, _, _ = unc.group_sums(g, rows["V"].to_numpy()[:, None], None, 1e6)
        act = _active(rows, g, o)
        kappa = unc.calibrate_kappa(o[act], mean[act], (vn + vm)[act])
        raw = evaluate(rows, mem, theta, 1.0, True)[CAL_SCALE]["coverage90"]
        kscale = kappa_by_scale(rows, mem, theta)
    res = {"loyo": evaluate(rows, mem, theta, kappa, prob), "season_loyo": season_errors(rows, mem),
           "theta": theta, "kappa": kappa, "kappa_raw_coverage": raw}
    if prob:
        res["kappa_scale"] = kscale
        res["loyo_scaled_coverage"] = {k: _cov_scaled(rows, mem, theta, kscale, k) for k in SCALES}
    if trow is not None and trow.height:
        res["out_of_window"] = evaluate(trow, tmem, theta, kappa, prob)
        res["season_out_of_window"] = season_errors(trow, tmem)
    return res


def kappa_by_scale(rows: pl.DataFrame, mem: np.ndarray, theta: float) -> dict:
    """kappa needed for 90 % coverage at each spatial scale, for weekly and yearly
    aggregates, indexed by the mean number of model cells per aggregate."""
    out = {"week": [], "year": []}
    for scale, cols in SCALES.items():
        g = _gkey(rows, cols)
        _, mean, vn, vm = unc.group_sums(g, mem, None, theta)
        _, o, _, _ = unc.group_sums(g, rows["V"].to_numpy()[:, None], None, 1e6)
        act = _active(rows, g, o)
        ncell = rows.with_columns(pl.Series("_g", g)).group_by("_g").agg(pl.col("h3_5").n_unique())["h3_5"].mean()
        k = unc.calibrate_kappa(o[act], mean[act], (vn + vm)[act], hi=12.0)
        out["year" if scale.endswith("year") else "week"].append({"scale": scale, "cells": float(ncell), "kappa": k})
    for v in out.values():
        v.sort(key=lambda r: r["cells"])
    return out


def kappa_for(kscale: dict | None, kind: str, n_cells: float, default: float) -> float:
    """Log-linear interpolation of kappa in the number of model cells."""
    pts = (kscale or {}).get(kind) or []
    if not pts:
        return default
    x = np.log([max(p["cells"], 1.0) for p in pts])
    y = np.array([p["kappa"] for p in pts])
    # coverage must never get worse with size: enforce non-decreasing kappa
    y = np.maximum.accumulate(y)
    return float(np.interp(np.log(max(n_cells, 1.0)), x, y))


def _cov_scaled(rows, mem, theta, kscale, scale) -> float:
    g = _gkey(rows, SCALES[scale])
    _, mean, vn, vm = unc.group_sums(g, mem, None, theta)
    _, o, _, _ = unc.group_sums(g, rows["V"].to_numpy()[:, None], None, 1e6)
    act = _active(rows, g, o)
    ncell = rows.with_columns(pl.Series("_g", g)).group_by("_g").agg(pl.col("h3_5").n_unique())["h3_5"].mean()
    k = kappa_for(kscale, "year" if scale.endswith("year") else "week", ncell, 1.0)
    return unc.coverage(o[act], mean[act], (vn + vm)[act], k)


def recalibrate(ctx: Context | None = None) -> dict:
    """Recompute scores and kappas from cached predictions (no refitting) and
    propagate theta/kappa to the serving metadata."""
    rep = load_report()
    if rep is None:
        raise RuntimeError("no validation report")
    for variant, models in rep["variants"].items():
        for name in list(models):
            rows, mem = _load_pred(f"oof_{variant}_{name}")
            if rows is None:
                continue
            trow, tmem = _load_pred(f"test_{variant}_{name}")
            models[name] = score(rows, mem, trow, tmem, prob=name in ("stratified_eb", "gbm"))
    if ctx is not None:
        rep["viirs_continuity"] = viirs_continuity(ctx, "N20")
        rep["viirs_continuity_n21"] = viirs_continuity(ctx, "N21")
    rep["recalibrated"] = time.strftime("%Y-%m-%d %H:%M")
    REPORT.write_text(json.dumps(rep, indent=2, default=float))
    meta_p = config.MODELS / "meta.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text())
        meta.setdefault("kappa_scale", {})
        for v in ("TA", "T", "A"):
            g = rep["variants"].get(v if v != "A" else "T", {}).get("gbm", {})
            if g.get("kappa"):
                meta["theta"][v], meta["kappa"][v] = g["theta"], g["kappa"]
                meta["kappa_scale"][v] = g.get("kappa_scale")
        for s, key in (("N20", "viirs_continuity"), ("N21", "viirs_continuity_n21")):
            vc = rep.get(key) or rep.get("viirs_continuity") or {}
            if vc.get("kappa"):
                meta["theta"][s], meta["kappa"][s] = vc["theta"], vc["kappa"]
                meta["kappa_scale"][s] = vc.get("kappa_scale")
        meta_p.write_text(json.dumps(meta, indent=2, default=float))
    return rep
