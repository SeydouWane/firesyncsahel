"""Prévision IA — harmonised fire activity for the next 1-4 weeks.

Machine-learning early warning built on the 25-year harmonised series.

Target   H(cell, t+h), h = 1..4 weeks, cell = H3 res-5 (~250 km²).
Features (all known at issue time t)
  * climatology of the target week (3-week smoothed, leave-target-year-out)
  * recent activity: last week, last 4 weeks, and its ratio to normal
  * season-to-date cumulative ratio to normal (fuel already burnt)
  * previous fire year's total ratio to normal
  * neighbourhood (H3 res-3 parent, ~12 000 km²) recent ratio to normal
  * season (target fire week, sin/cos), horizon, land cover (MCD12Q1), lat/lon
Model    Poisson gradient boosting (scikit-learn).
Validation  leave-one-fire-year-out on VIIRS-observed targets 2013-2024,
  against two baselines (climatology, persisted anomaly); skill on 4-week
  totals, Brier skill score and ROC AUC for "above normal" (> 75th
  percentile), and calibrated 90 % intervals.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import polars as pl
from . import config
from .config import GRID, WEEKS_PER_YEAR as W
from .grid import cell_center, geometry_to_cells, parents
from .harmonize import uncertainty as unc
from .stats import norm_cdf
from .ingest import boundaries, landcover

log = logging.getLogger(__name__)
OUT_JSON = config.MODELS / "forecast.json"
OUT_CELLS = config.MODELS / "forecast_cells.parquet"
HZ = (1, 2, 3, 4)
FIRST_TARGET_FY = 2012
EVAL_FY = tuple(range(2013, 2025))
GBM = dict(loss="poisson", learning_rate=0.07, max_iter=260, max_leaf_nodes=31, min_samples_leaf=60,
           l2_regularization=1.0, early_stopping=True, n_iter_no_change=15, validation_fraction=0.1)
FEATURES = ["sin", "cos", "fw_t", "h", "l_clim_t", "l_now", "l_prev", "l_sum4", "r_rec", "r_cum",
            "r_prevyr", "r_par", "l_climtot", "lat", "lon"] + [f"lc_{g}" for g in landcover.GROUPS]
# end-of-rainy-season fuel (MODIS MOD13A1 NDVI, max Aug-Oct of the fire year's start)
NDVI_FEATURES = ["ndvi_max", "ndvi_anom"]
FEATURE_SETS = {"base": FEATURES, "ndvi": FEATURES + NDVI_FEATURES}


# ------------------------------------------------------------------ cube
@dataclass
class Cube:
    cells: np.ndarray        # (C,) h3_5
    fyears: np.ndarray       # (K,)
    X: np.ndarray            # (C, K, W) harmonised weekly values, nan = no data
    complete: np.ndarray     # (K,) bool
    start_week: int
    h3_3: np.ndarray         # (C,) parent


def load_cube() -> Cube:
    meta = json.loads((config.MODELS / "meta.json").read_text())
    cw = pl.read_parquet(config.MODELS / "cell_week.parquet")
    cells = np.sort(cw["h3_5"].unique().to_numpy())
    fys = np.arange(cw["fyear"].min(), cw["fyear"].max() + 1)
    ci = np.searchsorted(cells, cw["h3_5"].to_numpy())
    ki = cw["fyear"].to_numpy() - fys[0]
    X = np.full((len(cells), len(fys), W), np.nan)
    X[ci, ki, cw["fweek"].to_numpy()] = cw["H"].to_numpy()
    # a fire year is complete when every week has data somewhere in the region
    has = np.isfinite(X).any(axis=0)  # (K, W)
    return Cube(cells, fys, X, has.all(axis=1), meta["start_week"], parents(cells, GRID.coarse_res))


def _smooth3(a: np.ndarray) -> np.ndarray:
    """Circular 3-week mean along the last axis (nan-aware)."""
    st = np.stack([np.roll(a, 1, -1), a, np.roll(a, -1, -1)])
    return np.nanmean(st, axis=0)


def climatology_loo(cb: Cube) -> np.ndarray:
    """clim[c, k, w]: mean over complete fire years other than k (3-week smoothed)."""
    Xc = np.where(cb.complete[None, :, None], cb.X, np.nan)
    S = np.nansum(Xc, axis=1)                        # (C, W)
    N = np.sum(np.isfinite(Xc), axis=1).astype(float)
    own = np.nan_to_num(Xc)
    own_n = np.isfinite(Xc).astype(float)
    clim = (S[:, None, :] - own) / np.maximum(N[:, None, :] - own_n, 1)
    return _smooth3(clim)


def climatology_full(cb: Cube) -> np.ndarray:
    Xc = np.where(cb.complete[None, :, None], cb.X, np.nan)
    return _smooth3(np.nanmean(Xc, axis=1))


# ------------------------------------------------------------------ features
def _flat(cb: Cube, arr: np.ndarray) -> np.ndarray:
    return arr.reshape(arr.shape[0], -1)


def feature_frame(cb: Cube, clim: np.ndarray, issues: list[tuple[int, int]], horizons=HZ,
                  sample: np.random.Generator | None = None) -> dict:
    """Build features for issue times (k, fw0) = data known through fire week fw0 of year index k."""
    C, K, _ = cb.X.shape
    Xf = _flat(cb, cb.X)                       # (C, K*W)
    Cf = _flat(cb, clim)
    Xz = np.nan_to_num(Xf)
    cumX = np.cumsum(np.nan_to_num(cb.X), axis=2)
    cumC = np.cumsum(clim, axis=2)
    tot = np.nansum(cb.X, axis=2)              # (C, K)
    climtot = np.nansum(clim, axis=2)          # (C, K)
    # parent aggregation
    par_ids, par_inv = np.unique(cb.h3_3, return_inverse=True)
    P = len(par_ids)

    def agg_par(a):  # (C, T) -> (P, T)
        out = np.zeros((P, a.shape[1]))
        np.add.at(out, par_inv, a)
        return out
    lc = landcover.load()
    lcd = {g: np.full(C, 1 / len(landcover.GROUPS)) for g in landcover.GROUPS}
    if lc is not None:
        m = dict(zip(lc["h3_5"].to_list(), range(lc.height)))
        idx = np.array([m.get(int(c), -1) for c in cb.cells])
        for g in landcover.GROUPS:
            col = lc[f"lc_{g}"].to_numpy()
            lcd[g] = np.where(idx >= 0, col[np.maximum(idx, 0)], 1 / len(landcover.GROUPS))
    ll = np.array([cell_center(int(c)) for c in cb.cells])
    # NDVI fuel per (cell, fire year): nan when unavailable (handled natively by the GBM)
    nd_max = np.full((C, K), np.nan)
    nd_anom = np.full((C, K), np.nan)
    try:
        from .ingest import ndvi
        nd = ndvi.load()
    except Exception:
        nd = None
    if nd is not None:
        ci = np.searchsorted(cb.cells, nd["h3_5"].to_numpy())
        ki = nd["year"].to_numpy() - cb.fyears[0]
        ok = (ci < C) & (ki >= 0) & (ki < K)
        ok &= cb.cells[np.minimum(ci, C - 1)] == nd["h3_5"].to_numpy()
        nd_max[ci[ok], ki[ok]] = nd["ndvi_max"].to_numpy()[ok]
        nd_anom[ci[ok], ki[ok]] = nd["ndvi_anom"].to_numpy()[ok]
    cols = {f: [] for f in FEATURES + NDVI_FEATURES + ["y", "cell", "k", "fw0", "kt", "fwt", "clim_t"]}
    XP, CP = agg_par(Xz), agg_par(np.nan_to_num(Cf))
    for (k, fw0) in issues:
        g0 = k * W + fw0
        if g0 < 3:
            continue
        sum4 = Xz[:, g0 - 3:g0 + 1].sum(1)
        clim4 = np.nan_to_num(Cf[:, g0 - 3:g0 + 1]).sum(1)
        r_rec = np.log((sum4 + 1) / (clim4 + 1))
        r_cum = np.log((cumX[:, k, fw0] + 1) / (cumC[:, k, fw0] + 1))
        r_prev = np.log((tot[:, k - 1] + 1) / (climtot[:, k - 1] + 1)) if k >= 1 else np.zeros(C)
        psum4 = XP[:, g0 - 3:g0 + 1].sum(1)
        pclim4 = CP[:, g0 - 3:g0 + 1].sum(1)
        r_par = np.log((psum4 + 1) / (pclim4 + 1))[par_inv]
        hs = horizons
        for h in hs:
            gt = g0 + h
            if gt >= K * W:
                continue
            kt, fwt = divmod(gt, W)
            take = np.ones(C, bool)
            if sample is not None:  # one random horizon per (cell, issue) in training
                take = sample.integers(0, len(horizons), C) == hs.index(h)
            if not take.any():
                continue
            ct = np.nan_to_num(Cf[:, gt])
            cols["sin"].append(np.full(take.sum(), np.sin(2 * np.pi * fwt / W)))
            cols["cos"].append(np.full(take.sum(), np.cos(2 * np.pi * fwt / W)))
            cols["fw_t"].append(np.full(take.sum(), fwt))
            cols["h"].append(np.full(take.sum(), h))
            cols["l_clim_t"].append(np.log1p(ct[take]))
            cols["l_now"].append(np.log1p(Xz[take, g0]))
            cols["l_prev"].append(np.log1p(Xz[take, g0 - 1]))
            cols["l_sum4"].append(np.log1p(sum4[take]))
            cols["r_rec"].append(r_rec[take]); cols["r_cum"].append(r_cum[take])
            cols["r_prevyr"].append(r_prev[take]); cols["r_par"].append(r_par[take])
            cols["l_climtot"].append(np.log1p(climtot[take, k]))
            cols["lat"].append(ll[take, 0]); cols["lon"].append(ll[take, 1])
            cols["ndvi_max"].append(nd_max[take, kt]); cols["ndvi_anom"].append(nd_anom[take, kt])
            for g in landcover.GROUPS:
                cols[f"lc_{g}"].append(lcd[g][take])
            cols["y"].append(Xf[take, gt]); cols["cell"].append(np.nonzero(take)[0])
            cols["k"].append(np.full(take.sum(), k)); cols["fw0"].append(np.full(take.sum(), fw0))
            cols["kt"].append(np.full(take.sum(), kt)); cols["fwt"].append(np.full(take.sum(), fwt))
            cols["clim_t"].append(ct[take])
    return {k: (np.concatenate(v) if v else np.array([])) for k, v in cols.items()}


def _matrix(f: dict, feats: list[str] = FEATURES) -> np.ndarray:
    return np.column_stack([f[c] for c in feats]).astype(np.float32)


def fit(f: dict, feats: list[str] = FEATURES, seed: int = 7) -> "HistGradientBoostingRegressor":
    from sklearn.ensemble import HistGradientBoostingRegressor  # training only (not on the web server)
    y = f["y"]
    ok = np.isfinite(y)
    rng = np.random.default_rng(seed)
    dead = (f["l_clim_t"] < 0.02) & (f["l_sum4"] == 0) & (y == 0)
    keep = ok & ((~dead) | (rng.random(len(y)) < 0.1))
    w = np.where(dead, 10.0, 1.0)[keep]
    m = HistGradientBoostingRegressor(random_state=seed, **GBM)
    m.fit(_matrix(f, feats)[keep], y[keep], sample_weight=w)
    return m


def _logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def platt_fit(p: np.ndarray, ev: np.ndarray) -> tuple[float, float]:
    from sklearn.linear_model import LogisticRegression
    lr = LogisticRegression(C=1e3).fit(_logit(p)[:, None], ev.astype(int))
    return float(lr.coef_[0, 0]), float(lr.intercept_[0])


def platt_apply(p, ab) -> np.ndarray:
    a, b = ab
    return 1 / (1 + np.exp(-(a * _logit(np.asarray(p, float)) + b)))


# ------------------------------------------------------------------ validation
def _issues(cb: Cube, k: int, last_fw: int = W - 1) -> list[tuple[int, int]]:
    return [(k, fw) for fw in range(3, last_fw + 1)]


def validate(cb: Cube, clim: np.ndarray) -> dict:
    """Leave-one-fire-year-out validation of every feature set (ablation);
    the set with the best zone 4-week skill is kept for operations."""
    t0 = time.time()
    k_of = {int(fy): i for i, fy in enumerate(cb.fyears)}
    train_k = [k_of[fy] for fy in cb.fyears if fy >= FIRST_TARGET_FY and fy in k_of]
    ftrain = feature_frame(cb, clim, [(k, fw) for k in train_k for fw in range(3, W)] +
                           [(k - 1, fw) for k in train_k for fw in range(W - 4, W)],
                           sample=np.random.default_rng(3))
    test = {}
    for fy in EVAL_FY:
        k = k_of[fy]
        if cb.complete[k]:
            test[k] = feature_frame(cb, clim, _issues(cb, k, W - 5))
    has_ndvi = np.isfinite(ftrain["ndvi_max"]).mean() > 0.5
    variants = {}
    for name, feats in FEATURE_SETS.items():
        if name == "ndvi" and not has_ndvi:
            continue
        variants[name] = _validate_set(cb, ftrain, test, feats, t0, name)
    # an extra predictor is kept only if it clearly helps: +0.5 pt of zone 4-week skill and no loss of BSS
    best = "base"
    if "ndvi" in variants:
        b, n = variants["base"], variants["ndvi"]
        if (n["zone_4wk"]["ml"]["skill_vs_clim"] >= b["zone_4wk"]["ml"]["skill_vs_clim"] + 0.005
                and n["above_normal"]["bss_ml"] >= b["above_normal"]["bss_ml"] - 0.002):
            best = "ndvi"
    out = dict(variants[best])
    out["feature_set"] = best
    out["ablation"] = {n: {"zone_4wk_skill": v["zone_4wk"]["ml"]["skill_vs_clim"],
                           "zone_week1_skill": v["zone_week1"]["ml"]["skill_vs_clim"],
                           "region_4wk_skill": v["region_4wk"]["ml"]["skill_vs_clim"],
                           "bss": v["above_normal"]["bss_ml"], "auc": v["above_normal"]["auc_ml"]}
                       for n, v in variants.items()}
    out["seconds"] = round(time.time() - t0, 1)
    return out


def _validate_set(cb: Cube, ftrain: dict, test: dict, feats: list[str], t0: float, name: str) -> dict:
    from sklearn.metrics import roc_auc_score
    rows = []
    for k, ft in test.items():
        sel = ftrain["kt"] != k
        m = fit({c: v[sel] for c, v in ftrain.items()}, feats)
        ok = np.isfinite(ft["y"])
        pred = m.predict(_matrix(ft, feats))
        persist = ft["clim_t"] * np.clip(np.exp(ft["r_rec"]), 0.25, 4)
        rows.append(pl.DataFrame({"cell": ft["cell"][ok], "k": ft["k"][ok], "fw0": ft["fw0"][ok], "h": ft["h"][ok],
                                  "y": ft["y"][ok], "ml": pred[ok], "clim": ft["clim_t"][ok], "pers": persist[ok]}))
        log.info("forecast LOYO [%s] %s done (%.0fs)", name, int(cb.fyears[k]), time.time() - t0)
    par = pl.DataFrame({"cell": np.arange(len(cb.cells)), "par": cb.h3_3})
    df = pl.concat(rows).join(par, on="cell")
    # region-level active season: issue weeks whose regional normal (4 weeks ahead) is >= 10 % of peak
    reg = df.group_by(["k", "fw0"]).agg(pl.col("clim").sum().alias("rc"))
    thr = 0.10 * reg["rc"].max()
    df = df.join(reg, on=["k", "fw0"]).filter(pl.col("rc") >= thr)
    out = {"years": list(EVAL_FY), "season_filter": "issue weeks whose regional normal >= 10 % of the peak",
           "n_rows": df.height}

    def scores(g: pl.DataFrame) -> dict:
        y = g["y"].to_numpy()
        r = {}
        for m in ("clim", "pers", "ml"):
            p = g[m].to_numpy()
            r[m] = {"mae": float(np.mean(np.abs(p - y))), "bias_pct": float(100 * (p.sum() - y.sum()) / max(y.sum(), 1)),
                    "r_log": float(np.corrcoef(np.log1p(p), np.log1p(y))[0, 1])}
        for m in ("pers", "ml"):
            r[m]["skill_vs_clim"] = float(1 - r[m]["mae"] / r["clim"]["mae"])
        r["n"] = int(len(y))
        return r

    # zone (res-3) 4-week totals and weekly; region 4-week totals
    z4 = df.group_by(["par", "k", "fw0"]).agg(pl.col("y", "ml", "clim", "pers").sum())
    zw = df.filter(pl.col("h") == 1).group_by(["par", "k", "fw0"]).agg(pl.col("y", "ml", "clim", "pers").sum())
    r4 = df.group_by(["k", "fw0"]).agg(pl.col("y", "ml", "clim", "pers").sum())
    out["zone_4wk"], out["zone_week1"], out["region_4wk"] = scores(z4), scores(zw), scores(r4)
    out["cell_week"] = scores(df)
    # dispersion + interval calibration on zone 4-week totals
    y, mu = z4["y"].to_numpy(), z4["ml"].to_numpy()
    theta = unc.nb_theta(y, mu)
    var = mu + mu ** 2 / theta
    kappa = unc.calibrate_kappa(y, mu, var)
    yw, muw = zw["y"].to_numpy(), zw["ml"].to_numpy()
    theta_w = unc.nb_theta(yw, muw)
    kappa_w = unc.calibrate_kappa(yw, muw, muw + muw ** 2 / theta_w)
    out["theta_4wk"], out["kappa_4wk"] = theta, kappa
    out["theta_week"], out["kappa_week"] = theta_w, kappa_w
    out["coverage_4wk"] = unc.coverage(y, mu, var, kappa)
    # above-normal events: zone 4-week total > p75 of the other years for the same weeks
    hist, hist90 = zone_history_p75(cb, z4, (75, 90))
    ev = (z4["y"].to_numpy() > hist)
    ev90 = (z4["y"].to_numpy() > hist90)
    p_raw = prob_above(mu, var * kappa ** 2, hist)
    p_raw90 = prob_above(mu, var * kappa ** 2, hist90)
    p_pers = prob_above(z4["pers"].to_numpy(), (z4["pers"].to_numpy() + z4["pers"].to_numpy() ** 2 / theta) * kappa ** 2, hist)
    # Platt recalibration, cross-fitted by fire year (each year calibrated on the others)
    ks = z4["k"].to_numpy()

    def cross_platt(p, e):
        q = np.empty_like(p)
        for k in np.unique(ks):
            o = ks != k
            q[~o] = platt_apply(p[~o], platt_fit(p[o], e[o]))
        return q
    p_ml = cross_platt(p_raw, ev)
    p_ml90 = cross_platt(p_raw90, ev90)
    b90 = float(np.mean((ev90.mean() - ev90) ** 2))
    out["well_above"] = {"event_rate": float(ev90.mean()),
                         "bss_ml": float(1 - np.mean((p_ml90 - ev90) ** 2) / b90),
                         "bss_raw": float(1 - np.mean((p_raw90 - ev90) ** 2) / b90),
                         "auc_ml": float(roc_auc_score(ev90, p_ml90)),
                         "reliability": reliability(p_ml90, ev90),
                         "platt": list(platt_fit(p_raw90, ev90))}
    base = np.full(len(ev), ev.mean())
    bs = lambda p: float(np.mean((p - ev) ** 2))
    out["above_normal"] = {
        "event_rate": float(ev.mean()),
        "brier_ml": bs(p_ml), "brier_raw": bs(p_raw), "brier_pers": bs(p_pers), "brier_clim": bs(base),
        "bss_ml": float(1 - bs(p_ml) / bs(base)), "bss_raw": float(1 - bs(p_raw) / bs(base)),
        "bss_pers": float(1 - bs(p_pers) / bs(base)),
        "auc_ml": float(roc_auc_score(ev, p_ml)), "auc_pers": float(roc_auc_score(ev, p_pers)),
        "reliability": reliability(p_ml, ev), "reliability_raw": reliability(p_raw, ev),
        "platt": list(platt_fit(p_raw, ev)),
    }
    out["features"] = feats
    return out


def zone_history_p75(cb: Cube, z4: pl.DataFrame, qs=(75,)) -> np.ndarray:
    """Percentile(s) over other complete years of each (zone, issue) 4-week total.
    One quantile -> (n,), several -> (len(qs), n)."""
    par_ids, par_inv = np.unique(cb.h3_3, return_inverse=True)
    ZX = np.zeros((len(par_ids), cb.X.shape[1], W))
    np.add.at(ZX, par_inv, np.nan_to_num(cb.X))
    Zf = ZX.reshape(len(par_ids), -1)
    pidx = {int(p): i for i, p in enumerate(par_ids)}
    out = np.empty((len(qs), z4.height))
    comp = np.nonzero(cb.complete)[0]
    for j, (p, k, fw0) in enumerate(zip(z4["par"].to_list(), z4["k"].to_list(), z4["fw0"].to_list())):
        i = pidx[int(p)]
        vals = [Zf[i, kk * W + fw0 + 1: kk * W + fw0 + 5].sum() for kk in comp if kk != k and kk * W + fw0 + 5 <= Zf.shape[1]]
        out[:, j] = np.percentile(vals, qs) if vals else np.inf
    return out[0] if len(qs) == 1 else out


def prob_above(mu, var, thr) -> np.ndarray:
    """P(X > thr) with log(X+1) Gaussian, moments matched (consistent with intervals)."""
    mu = np.maximum(np.asarray(mu, float), 0)
    v = np.maximum(np.asarray(var, float), mu)
    s2 = np.log1p(v / (mu + 1) ** 2)
    m = np.log(mu + 1) - s2 / 2
    return 1 - norm_cdf((np.log(np.asarray(thr, float) + 1) - m) / np.sqrt(np.maximum(s2, 1e-9)))


def reliability(p, ev, bins=5) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        s = (p >= a) & (p < b if b < 1 else p <= b)
        if s.sum():
            out.append({"p": float(p[s].mean()), "obs": float(ev[s].mean()), "n": int(s.sum())})
    return out


# ------------------------------------------------------------------ operational forecast
def issue_point(cb: Cube) -> tuple[int, int]:
    """Last fire week with data for (nearly) the whole region."""
    has = np.isfinite(cb.X).mean(axis=0)  # (K, W) share of cells with data
    ks, ws = np.nonzero(has > 0.9)
    g = (ks * W + ws).max()
    return divmod(int(g), W)


def week_start(cb: Cube, k: int, fw: int) -> date:
    from .seasonal import fire_week_start
    return fire_week_start(int(cb.fyears[k]), fw, cb.start_week)


def build(run_validation: bool = True) -> dict:
    cb = load_cube()
    clim_loo = climatology_loo(cb)
    report = json.loads(OUT_JSON.read_text()).get("validation") if OUT_JSON.exists() and not run_validation else None
    if run_validation:
        report = validate(cb, clim_loo)
    k_of = {int(fy): i for i, fy in enumerate(cb.fyears)}
    train_k = [k_of[fy] for fy in cb.fyears if fy >= FIRST_TARGET_FY]
    ftrain = feature_frame(cb, clim_loo, [(k, fw) for k in train_k for fw in range(3, W)] +
                           [(k - 1, fw) for k in train_k for fw in range(W - 4, W)],
                           sample=np.random.default_rng(11))
    fset = (report or {}).get("feature_set", "base")
    feats = FEATURE_SETS.get(fset, FEATURES)
    model = fit(ftrain, feats)
    k, fw0 = issue_point(cb)
    clim_full = climatology_full(cb)
    clim_now = clim_loo.copy()
    clim_now[:, k, :] = clim_full  # the running year is not in the complete-year mean anyway
    f = feature_frame(cb, clim_now, [(k, fw0)])
    mu = model.predict(_matrix(f, feats))
    out = pl.DataFrame({"h3_5": cb.cells[f["cell"]], "h": f["h"].astype(np.int8), "mu": mu,
                        "kt": f["kt"], "fwt": f["fwt"].astype(np.int8)})
    out.write_parquet(OUT_CELLS)
    issue ={"fyear": int(cb.fyears[k]), "fweek": fw0,
             "week_start": week_start(cb, k, fw0).isoformat(),
             "week_end": (week_start(cb, k, fw0) + timedelta(days=6)).isoformat(),
             "targets": [{"h": h, "start": week_start(cb, *divmod(k * W + fw0 + h, W)).isoformat(),
                          "fweek": (fw0 + h) % W} for h in HZ]}
    res = {"generated": time.strftime("%Y-%m-%d %H:%M"), "issue": issue, "validation": report,
           "features": feats, "feature_set": fset,
           "model": "HistGradientBoostingRegressor(loss=poisson) + Platt-calibrated exceedance probabilities"}
    OUT_JSON.write_text(json.dumps(res, indent=2, default=float))
    Forecaster.reset()
    res["units"] = Forecaster.get().units_overview("fr")
    return res


# ------------------------------------------------------------------ serving
RISK_ORDER = ["high", "moderate", "low", "offseason"]


class Forecaster:
    _inst = None

    @classmethod
    def get(cls) -> "Forecaster":
        if cls._inst is None:
            cls._inst = Forecaster()
        return cls._inst

    @classmethod
    def reset(cls):
        cls._inst = None

    def __init__(self):
        self.meta = json.loads(OUT_JSON.read_text())
        self.cb = load_cube()
        fc = pl.read_parquet(OUT_CELLS)
        self.mu = np.zeros((len(self.cb.cells), len(HZ)))
        ci = np.searchsorted(self.cb.cells, fc["h3_5"].to_numpy())
        self.mu[ci, fc["h"].to_numpy() - 1] = fc["mu"].to_numpy()
        self.share = pl.read_parquet(config.MODELS / "share_7.parquet")
        self._units = {}

    def weights(self, geom) -> np.ndarray:
        """Share of each model cell inside the zone (VIIRS-climatology weighted)."""
        c7 = geometry_to_cells(geom, GRID.fine_res)
        c5 = parents(c7, GRID.model_res)
        tot5 = self.share.group_by("h3_5").agg(pl.col("tot").first())
        sh = (pl.DataFrame({"h3_7": c7, "h3_5": c5}).join(self.share.select("h3_7", "share"), on="h3_7", how="left")
              .join(tot5, on="h3_5", how="left")
              .with_columns(pl.col("share").fill_null(
                  pl.when(pl.col("tot").is_not_null()).then(0.5 / (pl.col("tot") + 24.5)).otherwise(1 / 49)))
              .group_by("h3_5").agg(pl.col("share").sum().clip(0, 1)))
        w = np.zeros(len(self.cb.cells))
        idx = np.searchsorted(self.cb.cells, sh["h3_5"].to_numpy())
        ok = (idx < len(self.cb.cells)) & (self.cb.cells[np.minimum(idx, len(self.cb.cells) - 1)] == sh["h3_5"].to_numpy())
        w[idx[ok]] = sh["share"].to_numpy()[ok]
        return w

    def zone(self, w: np.ndarray, lang: str = "fr", name: str = "Zone") -> dict:
        v = self.meta["validation"] or {}
        th4, ka4 = v.get("theta_4wk", 3.0), v.get("kappa_4wk", 1.5)
        thw, kaw = v.get("theta_week", 2.0), v.get("kappa_week", 1.5)
        pl75 = (v.get("above_normal") or {}).get("platt")
        pl90 = (v.get("well_above") or {}).get("platt")
        cal = lambda p, ab: float(platt_apply(p, ab)) if ab else p
        iss = self.meta["issue"]
        k = int(np.nonzero(self.cb.fyears == iss["fyear"])[0][0])
        fw0 = iss["fweek"]
        mu_h = w @ self.mu                                   # (4,)
        ZX = np.tensordot(w, np.nan_to_num(self.cb.X), axes=(0, 0))  # (K, W)
        Zf = ZX.reshape(-1)
        comp = [kk for kk in np.nonzero(self.cb.complete)[0] if kk != k]
        g0 = k * W + fw0

        def hist(a, b):  # totals over issue+a .. issue+b for complete years
            return np.array([Zf[kk * W + fw0 + a: kk * W + fw0 + b + 1].sum() for kk in comp
                             if kk * W + fw0 + b + 1 <= len(Zf)])
        weeks = []
        for h in HZ:
            m = float(mu_h[h - 1])
            lo, hi = unc.interval(np.array([m]), np.array([m + m * m / thw]), kaw)
            hh = hist(h, h)
            weeks.append({"h": h, "start": iss["targets"][h - 1]["start"], "mu": m, "lo": float(lo[0]), "hi": float(hi[0]),
                          "p25": float(np.percentile(hh, 25)) if len(hh) else None,
                          "p50": float(np.percentile(hh, 50)) if len(hh) else None,
                          "p75": float(np.percentile(hh, 75)) if len(hh) else None})
        def block(n):
            m = float(mu_h[:n].sum())
            var = m + m * m / th4
            lo, hi = unc.interval(np.array([m]), np.array([var]), ka4)
            hh = hist(1, n)
            p50, p75, p90 = (np.percentile(hh, q) for q in (50, 75, 90)) if len(hh) else (np.nan,) * 3
            pa = cal(float(prob_above(np.array([m]), np.array([var * ka4 ** 2]), np.array([p75]))[0]), pl75) if len(hh) else None
            pb = cal(float(prob_above(np.array([m]), np.array([var * ka4 ** 2]), np.array([p90]))[0]), pl90) if len(hh) else None
            if pa is not None and pb is not None:
                pb = min(pb, pa)  # P(> p90) can never exceed P(> p75)
            ratio = (m + 1) / (p50 + 1) if np.isfinite(p50) else None
            return {"mu": m, "lo": float(lo[0]), "hi": float(hi[0]), "normal": float(p50), "p75": float(p75),
                    "p90": float(p90), "prob_above": pa, "prob_well_above": pb, "ratio": ratio,
                    "risk": risk(m, p50, pa, ratio)}
        recent = [{"start": week_start(self.cb, *divmod(g0 - j, W)).isoformat(),
                   "value": float(Zf[g0 - j]), "normal": float(np.median([Zf[kk * W + ((g0 - j) % W)] for kk in comp]))}
                  for j in range(7, -1, -1)]
        out = {"issue": iss, "weeks": weeks, "next2": block(2), "next4": block(4), "recent": recent}
        out["message"] = alert_message(name, out, lang)
        return out

    def units_overview(self, lang: str = "fr") -> dict:
        if lang in self._units:
            return self._units[lang]
        rows = []
        for lvl in (1, 2):
            gj = boundaries.load(lvl) or {"features": []}
            for f in gj["features"]:
                p = f["properties"]
                key = ("w", p["id"])
                if key not in self._units:
                    self._units[key] = self.weights(f["geometry"])
                z = self.zone(self._units[key], lang, p["name"])
                rows.append({"id": p["id"], "name": p["name"], "level": lvl, "iso3": p["iso3"],
                             "parent": p.get("parent"), "next2": z["next2"], "next4": z["next4"],
                             "weeks": [{k: w[k] for k in ("mu", "p50")} for w in z["weeks"]],
                             "message": z["message"]})
        wr = np.ones(len(self.cb.cells))
        region = self.zone(wr, lang, "Sénégal & Gambie" if lang == "fr" else "Senegal & The Gambia")
        res = {"issue": self.meta["issue"], "generated": self.meta["generated"], "units": rows, "region": region,
               "validation": self.meta.get("validation")}
        self._units[lang] = res
        return res


MIN_FIRES = 10  # below this many expected detections an anomaly is not actionable


def risk(mu: float, normal: float, p_above: float | None, ratio: float | None) -> str:
    """Level of the coming weeks against the zone's own history.

    high / moderate: activity clearly above normal AND a material number of fires
    low:             activity near or below normal (labelled "normal or below")
    offseason:       too little activity to act on (labelled "low activity")
    Probabilities are Platt-calibrated: the base rate of "> p75" is 25 %.
    A ratio alone needs an absolute excess too, so 5 fires vs a normal of 1 is not an alert."""
    nrm = normal if normal is not None and np.isfinite(normal) else 0.0
    if mu < MIN_FIRES and nrm < 1.5 * MIN_FIRES:
        return "offseason"
    p, r, excess = p_above or 0, ratio or 0, mu - nrm
    if mu < MIN_FIRES:
        return "low"
    if p >= 0.45 or (r >= 1.5 and excess >= 15):
        return "high"
    if p >= 0.33 or (r >= 1.15 and excess >= 8):
        return "moderate"
    return "low"


def _d(iso: str, lang: str) -> str:
    d = date.fromisoformat(iso)
    mo = (["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"] if lang == "fr"
          else ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    return f"{d.day} {mo[d.month - 1]}"


def alert_message(name: str, z: dict, lang: str = "fr") -> str:
    """Short SMS / WhatsApp text for local fire committees (<= ~200 chars)."""
    b = z["next2"]
    end = (date.fromisoformat(z["issue"]["targets"][1]["start"]) + timedelta(days=6)).isoformat()
    n = int(round(b["mu"]))
    ratio = b["ratio"] or 1
    if lang == "fr":
        lvl = {"high": "risque feux ÉLEVÉ", "moderate": "risque feux MODÉRÉ",
               "low": "activité feux NORMALE", "offseason": "activité feux FAIBLE"}[b["risk"]]
        act = {"high": "Renforcez pare-feux et patrouilles, sensibilisez les villages.",
               "moderate": "Vérifiez les pare-feux et la mobilisation des comités.",
               "low": "Maintenez le dispositif habituel.", "offseason": "Pas d'action particulière."}[b["risk"]]
        return (f"FireSync {name} : {lvl} jusqu'au {_d(end, 'fr')}. "
                f"~{n} feux attendus ({ratio:.1f}x la normale). {act}")
    lvl = {"high": "fire risk HIGH", "moderate": "fire risk MODERATE",
           "low": "fire activity NORMAL", "offseason": "fire activity LOW"}[b["risk"]]
    act = {"high": "Reinforce firebreaks and patrols, alert villages.",
           "moderate": "Check firebreaks and committee readiness.",
           "low": "Keep the usual set-up.", "offseason": "No specific action."}[b["risk"]]
    return f"FireSync {name}: {lvl} until {_d(end, 'en')}. ~{n} fires expected ({ratio:.1f}x normal). {act}"
