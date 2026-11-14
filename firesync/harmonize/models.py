"""Cross-sensor harmonisation models (MODIS -> VIIRS S-NPP equivalent).

Four models share one interface so they can be validated side by side:

* ``Naive``        collage naïf: MODIS counts used as they are.
* ``SingleRatio``  one regional ratio  sum(VIIRS) / sum(MODIS)  (state of the art
                   of "harmonised calendars" over large regions).
* ``StratifiedEB`` ratio per (cell x season) shrunk towards (land cover x season)
                   then towards season with gamma-Poisson empirical Bayes, plus a
                   background rate for weeks where MODIS sees nothing.
* ``GBMEnsemble``  Poisson gradient boosting on MODIS counts, FRP, day/night
                   mix, neighbouring weeks and cells, season, land cover and
                   cell-level priors (incl. matched-overpass ratio); a bootstrap
                   over *years* provides the model-uncertainty members.

Every model exposes ``predict_members(X) -> (n, B)`` arrays of expected
S-NPP counts (B = 1 for deterministic models); uncertainty aggregation over
any zone is done from these members (see ``uncertainty.py``).

Feature variants: ``TA`` (Terra + Aqua, 2002-07 onwards), ``T`` (Terra only:
Nov 2000 - Jul 2002 and Aqua outages) and ``A`` (Aqua only: Terra outages).
"""
from __future__ import annotations

import numpy as np
import polars as pl

from ..config import MODEL
from ..grid import cell_center
from ..ingest.landcover import GROUPS
from ..seasonal import add_fire_year

VARIANTS = {"TA": ("T", "A"), "T": ("T",), "A": ("A",)}
SEASON_BIN = 4  # weeks per season bin for the stratified model
TARGET = "V"


# --------------------------------------------------------------------------
# Data preparation
# --------------------------------------------------------------------------
def prepare(mt: pl.DataFrame, week_av: pl.DataFrame, lc: pl.DataFrame | None,
            paired: pl.DataFrame | None, start_week: int, min_frac: float = 0.5
            ) -> pl.DataFrame:
    """Join availability, adjust partial weeks, derive base variables."""
    d = mt.join(week_av, on=["year", "week"], how="left")
    for s in ("MODIS_T", "MODIS_A", "VIIRS_SNPP", "VIIRS_N20", "VIIRS_N21"):
        d = d.with_columns(pl.col(f"f_{s}").fill_null(0.0))
    def adj(n, f):
        return (pl.when(pl.col(f) >= min_frac).then(pl.col(n) / pl.col(f)).otherwise(None))
    d = d.with_columns(
        adj("n_MODIS_T", "f_MODIS_T").alias("T"),
        adj("n_MODIS_A", "f_MODIS_A").alias("A"),
        adj("n_VIIRS_SNPP", "f_VIIRS_SNPP").alias("V"),
        adj("n_VIIRS_N20", "f_VIIRS_N20").alias("N20"),
        adj("n_VIIRS_N21", "f_VIIRS_N21").alias("N21"),
        adj("frp_MODIS_T", "f_MODIS_T").alias("FT"),
        adj("frp_MODIS_A", "f_MODIS_A").alias("FA"),
        (pl.col("n_night_MODIS_T") / pl.col("n_MODIS_T").clip(1, None)).alias("nightT"),
        (pl.col("n_night_MODIS_A") / pl.col("n_MODIS_A").clip(1, None)).alias("nightA"),
        (pl.col("week") // SEASON_BIN).clip(0, 12).cast(pl.Int8).alias("sbin"),
    )
    d = add_fire_year(d, start_week)
    d = d.sort(["h3_5", "year", "week"])
    # neighbouring weeks (dense grid => shift over the cell is a weekly lag)
    for v in ("T", "A"):
        d = d.with_columns(
            pl.col(v).shift(1).over("h3_5").alias(f"{v}_prev"),
            pl.col(v).shift(-1).over("h3_5").alias(f"{v}_next"),
            pl.col(v).sum().over(["h3_3", "year", "week"]).alias(f"{v}_par"),
        )
    # cell centre and land cover
    cells = d.select("h3_5").unique()
    ll = np.array([cell_center(int(c)) for c in cells["h3_5"].to_list()])
    cells = cells.with_columns(pl.Series("lat", ll[:, 0]), pl.Series("lon", ll[:, 1]))
    if lc is not None:
        cells = cells.join(lc, on="h3_5", how="left")
    for g in GROUPS:
        col = f"lc_{g}"
        if col not in cells.columns:
            cells = cells.with_columns(pl.lit(None, pl.Float64).alias(col))
        cells = cells.with_columns(pl.col(col).fill_null(1.0 / len(GROUPS)))
    if "lc_major" not in cells.columns:
        cells = cells.with_columns(pl.lit(5, pl.Int8).alias("lc_major"))
    cells = cells.with_columns(pl.col("lc_major").fill_null(5))
    d = d.join(cells, on="h3_5", how="left")
    if paired is not None and paired.height:
        pa = (paired.filter(pl.col("pair") == "A_SNPP")
              .select("h3_5", "year", "week", pl.col("n_src").alias("pA"),
                      pl.col("n_ref").alias("pV")))
        d = d.join(pa, on=["h3_5", "year", "week"], how="left")
    else:
        d = d.with_columns(pl.lit(None, pl.Int64).alias("pA"), pl.lit(None, pl.Int64).alias("pV"))
    d = d.with_columns(pl.col("pA").fill_null(0), pl.col("pV").fill_null(0))
    return d


def m_expr(variant: str) -> pl.Expr:
    parts = VARIANTS[variant]
    return sum(pl.col(p) for p in parts)


def usable(d: pl.DataFrame, variant: str, need_target: bool) -> pl.Expr:
    e = pl.lit(True)
    for p in VARIANTS[variant]:
        e = e & pl.col(p).is_not_null()
    if need_target:
        e = e & pl.col(TARGET).is_not_null()
    return e


# --------------------------------------------------------------------------
# Cell-level priors (target encoding), computed from training years only
# --------------------------------------------------------------------------
def _cell_year_sums(d: pl.DataFrame, variant: str) -> pl.DataFrame:
    M = m_expr(variant)
    return (d.filter(usable(d, variant, True))
            .group_by(["h3_5", "fyear"])
            .agg(pl.col(TARGET).sum().alias("SV"), M.sum().alias("SM"),
                 pl.when(M == 0).then(pl.col(TARGET)).otherwise(0).sum().alias("SV0"),
                 (M == 0).sum().alias("N0"),
                 pl.col("pV").sum().alias("SPV"), pl.col("pA").sum().alias("SPA")))


def priors(d: pl.DataFrame, variant: str, years, loo: bool) -> pl.DataFrame:
    """Shrunk log ratio, log background rate and log matched-overpass ratio.

    With ``loo=True`` the priors of a (cell, fire year) exclude that year, so
    that training rows never see their own target.
    """
    a = MODEL.eb_prior_strength
    cy = _cell_year_sums(d, variant).filter(pl.col("fyear").is_in(list(years)))
    tot = cy.group_by("h3_5").agg(pl.col(c).sum() for c in ("SV", "SM", "SV0", "N0", "SPV", "SPA"))
    g = cy.select(pl.col(c).sum() for c in ("SV", "SM", "SV0", "N0", "SPV", "SPA")).row(0, named=True)
    r0 = g["SV"] / max(g["SM"], 1)
    l0 = g["SV0"] / max(g["N0"], 1)
    i0 = g["SPV"] / max(g["SPA"], 1) if g["SPA"] else r0

    def enc(df):
        return df.with_columns(
            ((pl.col("SV") + a * r0) / (pl.col("SM") + a)).log().alias("p_lr"),
            ((pl.col("SV0") + 20 * l0) / (pl.col("N0") + 20)).log().alias("p_lbg"),
            ((pl.col("SPV") + a * i0) / (pl.col("SPA") + a)).log().alias("p_linst"),
        ).select("h3_5", *([c for c in ("fyear",) if c in df.columns]), "p_lr", "p_lbg", "p_linst")

    if not loo:
        return enc(tot)
    own = cy.join(tot, on="h3_5", suffix="_t")
    for c in ("SV", "SM", "SV0", "N0", "SPV", "SPA"):
        own = own.with_columns((pl.col(f"{c}_t") - pl.col(c)).alias(c))
    return enc(own.select("h3_5", "fyear", "SV", "SM", "SV0", "N0", "SPV", "SPA"))


def defaults_for_priors(variant: str, d: pl.DataFrame, years) -> dict:
    p = priors(d, variant, years, loo=False)
    return {c: float(p[c].median()) for c in ("p_lr", "p_lbg", "p_linst")}


# --------------------------------------------------------------------------
# Feature matrix
# --------------------------------------------------------------------------
def feature_names(variant: str) -> list[str]:
    f = []
    for p in VARIANTS[variant]:
        f += [f"l{p}", f"lF{p}", f"night{p}", f"l{p}_prev", f"l{p}_next", f"l{p}_par"]
    f += ["sin_w", "cos_w", "lat", "lon"] + [f"lc_{g}" for g in GROUPS]
    f += ["p_lr", "p_lbg", "p_linst"]
    return f


def features(d: pl.DataFrame, variant: str, pri: pl.DataFrame, fill: dict) -> np.ndarray:
    on = ["h3_5", "fyear"] if "fyear" in pri.columns else ["h3_5"]
    x = d.join(pri, on=on, how="left").with_columns(
        [pl.col(c).fill_null(v) for c, v in fill.items()])
    ex = []
    for p in VARIANTS[variant]:
        ex += [pl.col(p).log1p().alias(f"l{p}"),
               pl.col(f"F{p}").fill_null(0).log1p().alias(f"lF{p}"),
               pl.col(f"night{p}").alias(f"night{p}"),
               pl.col(f"{p}_prev").fill_null(pl.col(p)).log1p().alias(f"l{p}_prev"),
               pl.col(f"{p}_next").fill_null(pl.col(p)).log1p().alias(f"l{p}_next"),
               pl.col(f"{p}_par").fill_null(0).log1p().alias(f"l{p}_par")]
    ang = 2 * np.pi * pl.col("week").cast(pl.Float64) / 52.0
    ex += [ang.sin().alias("sin_w"), ang.cos().alias("cos_w")]
    x = x.with_columns(ex)
    return x.select(feature_names(variant)).to_numpy().astype(np.float32)


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class Naive:
    name = "naive"
    label = {"fr": "Collage naïf", "en": "Naive splice"}

    def __init__(self, variant: str = "TA"):
        self.variant = variant

    def fit(self, d, years):
        return self

    def predict_members(self, d):
        return d.select(m_expr(self.variant)).to_numpy().astype(np.float32)


class SingleRatio(Naive):
    name = "single_ratio"
    label = {"fr": "Ratio unique", "en": "Single ratio"}

    def fit(self, d, years):
        t = d.filter(usable(d, self.variant, True) & pl.col("fyear").is_in(list(years)))
        self.r = float(t[TARGET].sum() / max(t.select(m_expr(self.variant)).to_series().sum(), 1))
        return self

    def predict_members(self, d):
        return (d.select(m_expr(self.variant)).to_numpy() * self.r).astype(np.float32)


class StratifiedEB(Naive):
    name = "stratified_eb"
    label = {"fr": "Ratio stratifié (Bayes empirique)", "en": "Stratified ratio (empirical Bayes)"}

    def __init__(self, variant: str = "TA", n_draws: int = 16, seed: int = MODEL.random_state):
        super().__init__(variant)
        self.n_draws, self.seed = n_draws, seed

    def fit(self, d, years):
        a, b = MODEL.eb_prior_strength, 20.0
        M = m_expr(self.variant)
        t = (d.filter(usable(d, self.variant, True) & pl.col("fyear").is_in(list(years)))
             .with_columns(M.alias("_M")))
        pos, zer = t.filter(pl.col("_M") > 0), t.filter(pl.col("_M") == 0)
        s = pos.group_by("sbin").agg(pl.col("V").sum().alias("sv"), pl.col("_M").sum().alias("sm"))
        s = s.with_columns((pl.col("sv") / pl.col("sm")).alias("r_s"))
        k = (pos.group_by(["lc_major", "sbin"]).agg(pl.col("V").sum().alias("kv"),
                                                    pl.col("_M").sum().alias("km"))
             .join(s.select("sbin", "r_s"), on="sbin")
             .with_columns(((pl.col("kv") + a * pl.col("r_s")) / (pl.col("km") + a)).alias("r_k")))
        c = pos.group_by(["h3_5", "lc_major", "sbin"]).agg(pl.col("V").sum().alias("cv"),
                                                           pl.col("_M").sum().alias("cm"))
        zs = zer.group_by("sbin").agg((pl.col("V").sum() / pl.len()).alias("l_s"))
        zk = (zer.group_by(["lc_major", "sbin"]).agg(pl.col("V").sum().alias("kv0"),
                                                     pl.len().alias("kn0"))
              .join(zs, on="sbin")
              .with_columns(((pl.col("kv0") + b * pl.col("l_s")) / (pl.col("kn0") + b)).alias("l_k")))
        zc = zer.group_by(["h3_5", "sbin"]).agg(pl.col("V").sum().alias("cv0"),
                                               pl.len().alias("cn0"))
        self.s, self.k, self.c, self.zs, self.zk, self.zc = s, k, c, zs, zk, zc
        self.a, self.b = a, b
        return self

    def _params(self, d):
        a, b = self.a, self.b
        x = (d.select("h3_5", "lc_major", "sbin", m_expr(self.variant).alias("_M"))
             .with_row_index("_i")
             .join(self.s.select("sbin", "r_s"), on="sbin", how="left")
             .join(self.k.select("lc_major", "sbin", "r_k"), on=["lc_major", "sbin"], how="left")
             .join(self.c.select("h3_5", "sbin", "cv", "cm"), on=["h3_5", "sbin"], how="left")
             .join(self.zs, on="sbin", how="left")
             .join(self.zk.select("lc_major", "sbin", "l_k"), on=["lc_major", "sbin"], how="left")
             .join(self.zc, on=["h3_5", "sbin"], how="left")
             .sort("_i"))
        r_s_glob = float(self.s["sv"].sum() / max(self.s["sm"].sum(), 1))
        x = x.with_columns(
            pl.col("r_s").fill_null(r_s_glob), pl.col("l_s").fill_null(0.0)).with_columns(
            pl.col("r_k").fill_null(pl.col("r_s")), pl.col("l_k").fill_null(pl.col("l_s")),
            pl.col("cv").fill_null(0), pl.col("cm").fill_null(0),
            pl.col("cv0").fill_null(0), pl.col("cn0").fill_null(0))
        # gamma posterior: shape, rate
        sh_r = (x["cv"] + a * x["r_k"]).to_numpy()
        rt_r = (x["cm"] + a).to_numpy()
        sh_l = (x["cv0"] + b * x["l_k"]).to_numpy()
        rt_l = (x["cn0"] + b).to_numpy()
        return x["_M"].to_numpy(), sh_r, rt_r, sh_l, rt_l

    def predict_members(self, d):
        from scipy.stats import gamma
        M, sh_r, rt_r, sh_l, rt_l = self._params(d)
        pos = M > 0
        out = np.empty((len(M), self.n_draws), dtype=np.float32)
        # One posterior draw per (cell, season bin) and member: the same draw is
        # reused for every week/year of that cell-season (the ratio is a
        # parameter, not noise) while different cells stay independent. The
        # uniform comes from a hash so that any subset of rows gets the same draw.
        key = d.select(pl.struct(["h3_5", "sbin"]).alias("k"))["k"]
        for j in range(self.n_draws):
            h = key.hash(seed=self.seed + 7919 * j).to_numpy()
            u = ((h >> np.uint64(11)).astype(np.float64) + 0.5) / float(2 ** 53)
            rr = gamma.ppf(u, np.maximum(sh_r, 1e-6)) / rt_r
            ll = gamma.ppf(u, np.maximum(sh_l, 1e-6)) / rt_l
            out[:, j] = np.where(pos, rr * M, ll)
        return out


class GBMEnsemble(Naive):
    name = "gbm"
    label = {"fr": "Gradient boosting stratifié (ensemble)", "en": "Stratified gradient boosting (ensemble)"}

    def __init__(self, variant: str = "TA", n_members: int = MODEL.n_bootstrap,
                 seed: int = MODEL.random_state):
        super().__init__(variant)
        self.n_members, self.seed = n_members, seed

    def fit(self, d, years):
        years = sorted(years)
        tr = d.filter(usable(d, self.variant, True) & pl.col("fyear").is_in(years))
        # subsample "dead" rows (no fire anywhere around) with inverse weights
        rng = np.random.default_rng(self.seed)
        dead = pl.col(TARGET) == 0
        for p in VARIANTS[self.variant]:
            dead = dead & (pl.col(p) == 0) & (pl.col(f"{p}_prev").fill_null(0) == 0) \
                & (pl.col(f"{p}_next").fill_null(0) == 0)
        is_dead = tr.select(dead).to_series().to_numpy()
        u = rng.random(len(is_dead))
        keep_rows = (~is_dead) | (u < MODEL.dead_keep)
        base_w = np.where(is_dead, 1.0 / MODEL.dead_keep, 1.0)[keep_rows]
        tr = tr.filter(pl.Series(keep_rows))
        self.fill = defaults_for_priors(self.variant, d, years)
        self.pri_pred = priors(d, self.variant, years, loo=False)
        pri_tr = priors(d, self.variant, years, loo=True)
        X = features(tr, self.variant, pri_tr, self.fill)
        from sklearn.ensemble import HistGradientBoostingRegressor  # training only (not on the web server)
        y = tr[TARGET].to_numpy().astype(np.float64)
        fy = tr["fyear"].to_numpy()
        self.members = []
        for b in range(self.n_members):
            sample = rng.choice(years, size=len(years), replace=True)
            w_year = {yy: int((sample == yy).sum()) for yy in years}
            w = np.array([w_year[v] for v in fy], dtype=np.float64) * base_w
            keep = w > 0
            m = HistGradientBoostingRegressor(random_state=self.seed + b, **MODEL.gbm_params)
            m.fit(X[keep], y[keep], sample_weight=w[keep])
            self.members.append(m)
        self.feature_names = feature_names(self.variant)
        return self

    def predict_members(self, d):
        X = features(d, self.variant, self.pri_pred, self.fill)
        return np.column_stack([m.predict(X) for m in self.members]).astype(np.float32)


MODEL_CLASSES = {c.name: c for c in (Naive, SingleRatio, StratifiedEB, GBMEnsemble)}


# --------------------------------------------------------------------------
# VIIRS -> VIIRS (NOAA-20 / NOAA-21 -> S-NPP equivalent)
# --------------------------------------------------------------------------
class ViirsRatio:
    """Empirical-Bayes S-NPP / successor ratio per (cell x season bin)."""

    def __init__(self, src: str):
        self.src = src  # "N20" | "N21"

    def fit(self, d: pl.DataFrame, years=None):
        a = 50.0
        t = d.filter(pl.col(self.src).is_not_null() & pl.col("V").is_not_null())
        if years is not None:
            t = t.filter(pl.col("fyear").is_in(list(years)))
        self.n_train = t.height
        if t.height == 0 or t[self.src].sum() == 0:
            self.ok = False
            return self
        self.ok = True
        s = t.group_by("sbin").agg((pl.col("V").sum() / pl.col(self.src).sum()).alias("r_s"))
        c = t.group_by(["h3_5", "sbin"]).agg(pl.col("V").sum().alias("cv"),
                                             pl.col(self.src).sum().alias("cn"))
        self.r_glob = float(t["V"].sum() / t[self.src].sum())
        self.tab = (c.join(s, on="sbin")
                    .with_columns(((pl.col("cv") + a * pl.col("r_s")) / (pl.col("cn") + a)).alias("r"),
                                  ((pl.col("cv") + a * pl.col("r_s")).sqrt() / (pl.col("cn") + a)).alias("r_sd"))
                    .select("h3_5", "sbin", "r", "r_sd"))
        self.s = s
        return self

    def ratios(self, d: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        x = (d.select("h3_5", "sbin").with_row_index("_i")
             .join(self.tab, on=["h3_5", "sbin"], how="left")
             .join(self.s, on="sbin", how="left").sort("_i")
             .with_columns(pl.col("r").fill_null(pl.col("r_s")).fill_null(self.r_glob),
                           pl.col("r_sd").fill_null(0.05)))
        return x["r"].to_numpy(), x["r_sd"].to_numpy()
