"""Zone query engine: harmonised weekly series + calendar indicators for any polygon.

The zone is rasterised onto H3 res-7 cells (~5 km²). For every week the
reference S-NPP-equivalent count is taken from:

* VIIRS S-NPP observations inside the zone (exact, no model);
* NOAA-20 / NOAA-21 observations x cell-season ratio (after S-NPP, gaps);
* the MODIS model members of each res-5 cell, allocated to the zone with
  weight a = MODIS detections inside the zone / MODIS detections of the cell
  (or the cell's VIIRS climatological share when MODIS saw nothing).

Because members are summed before computing the spread, the uncertainty of
any aggregate (week, season, year) keeps the spatial and temporal correlation
of the model error; the kappa factors come from the leave-one-year-out
calibration (validation report).
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import polars as pl

from . import config, indicators
from .config import GRID, SEASON, WEEKS_PER_YEAR
from .grid import geometry_to_cells, parents
from .harmonize import uncertainty as unc
from .processing import week_days
from .seasonal import detect_start_week

MIN_FRAC = 0.5
SRC_ORDER = ["VIIRS_SNPP", "N20", "N21", "TA", "T", "A"]


class Store:
    """Serving tables, loaded once (thread-safe lazy singleton)."""

    _lock = threading.Lock()
    _inst: "Store | None" = None

    @classmethod
    def get(cls) -> "Store":
        with cls._lock:
            if cls._inst is None:
                cls._inst = Store()
            return cls._inst

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._inst = None

    def __init__(self):
        M, P = config.MODELS, config.PROCESSED
        self.meta = json.loads((M / "meta.json").read_text())
        self.B = int(self.meta["members"])
        self.harm = pl.read_parquet(M / "harm_5.parquet")
        self.share = pl.read_parquet(M / "share_7.parquet")
        rp = M / "viirs_ratio.parquet"
        self.ratio = pl.read_parquet(rp) if rp.exists() else None
        self.week_av = pl.read_parquet(P / "availability_week.parquet")
        self.model_week = pl.read_parquet(
            P / "model_week.parquet",
            columns=["h3_5", "year", "week", "n_MODIS_T", "n_MODIS_A", "n_VIIRS_N20", "n_VIIRS_N21"])
        # weekly counts per H3 res-7 cell, in memory (zone queries filter it on every request)
        self.fine = pl.read_parquet(P / "fine_week.parquet", columns=["h3_7", "year", "week", "sensor", "n"])
        # individual detections, scanned lazily (map points, sensor coverage)
        dp = P / "det_serving.parquet"
        self.det = pl.scan_parquet(dp if dp.exists() else P / "detections.parquet").select(
            "sensor", "lon", "lat", "frp", "date", "year", "week")
        self.hex_year = pl.read_parquet(M / "hex_year.parquet")
        wa = self.week_av
        src = (pl.when(pl.col("f_VIIRS_SNPP") >= MIN_FRAC).then(pl.lit("VIIRS_SNPP"))
               .when(pl.col("f_VIIRS_N20") >= MIN_FRAC).then(pl.lit("N20"))
               .when(pl.col("f_VIIRS_N21") >= MIN_FRAC).then(pl.lit("N21"))
               .when((pl.col("f_MODIS_T") >= MIN_FRAC) & (pl.col("f_MODIS_A") >= MIN_FRAC)).then(pl.lit("TA"))
               .when(pl.col("f_MODIS_T") >= MIN_FRAC).then(pl.lit("T"))
               .when(pl.col("f_MODIS_A") >= MIN_FRAC).then(pl.lit("A"))
               .otherwise(None))
        self.weeks = (wa.with_columns(src.alias("source"))
                      .drop_nulls("source").sort(["year", "week"]))
        self.last_date = self._last_date()

    def _last_date(self) -> str:
        return str(self.det.select(pl.col("date").max()).collect().item())

    def coverage(self) -> list[tuple]:
        """(sensor, first date, last date, n detections) per sensor."""
        d = (self.det.group_by("sensor")
             .agg(pl.col("date").min().cast(pl.Utf8), pl.col("date").max().cast(pl.Utf8).alias("last"), pl.len())
             .with_columns(pl.col("sensor").cast(pl.Utf8)).sort("sensor").collect())
        return [tuple(r) for r in d.iter_rows()]

    def per_year(self) -> list[tuple]:
        d = (self.det.group_by(["year", "sensor"]).agg(pl.len())
             .with_columns(pl.col("sensor").cast(pl.Utf8)).sort(["year", "sensor"]).collect())
        return [tuple(r) for r in d.iter_rows()]

    def points(self, pairs: list[tuple[int, int]], limit: int) -> pl.DataFrame:
        """Detections of the given (calendar year, week) pairs."""
        sel = pl.DataFrame({"year": [p[0] for p in pairs], "week": [p[1] for p in pairs]},
                           schema={"year": pl.Int16, "week": pl.Int8})
        return (self.det.join(sel.lazy(), on=["year", "week"], how="semi")
                .select(pl.col("lon"), pl.col("lat"), pl.col("sensor").cast(pl.Utf8), pl.col("frp"))
                .head(limit).collect())


@dataclass
class ZoneData:
    weekly: pl.DataFrame          # year, week, source, value, lo, hi, ndays + raw sensors
    parts: list                   # (keys_df, members, kappa) for aggregation
    obs: pl.DataFrame             # observed VIIRS weeks (year, week, value)
    cells7: int
    area_km2: float


def _fine_counts(st: Store, cells7: np.ndarray) -> pl.DataFrame:
    return st.fine.filter(pl.col("h3_7").is_in(pl.Series(np.asarray(cells7, dtype=np.int64))))


def zone_data(geom, mode: str = "harmonized") -> ZoneData:
    st = Store.get()
    cells7 = geometry_to_cells(geom, GRID.fine_res)
    c5_of = parents(cells7, GRID.model_res)
    area = float(len(cells7) * 5.161)  # mean area of a res-7 cell (km²)
    fine = _fine_counts(st, cells7)
    if fine.height:
        fine = fine.with_columns(pl.Series("h3_5", parents(fine["h3_7"].to_numpy(), GRID.model_res)))
    else:
        fine = fine.with_columns(pl.lit(None, pl.Int64).alias("h3_5"))
    weeks = st.weeks
    raw = (fine.group_by(["year", "week", "sensor"]).agg(pl.col("n").sum())
           .pivot(on="sensor", index=["year", "week"], values="n") if fine.height
           else pl.DataFrame(schema={"year": pl.Int16, "week": pl.Int8}))
    for s in ("MODIS_T", "MODIS_A", "VIIRS_SNPP", "VIIRS_N20", "VIIRS_N21"):
        if s not in raw.columns:
            raw = raw.with_columns(pl.lit(0).alias(s))
    w = (weeks.join(raw, on=["year", "week"], how="left")
         .with_columns([pl.col(s).fill_null(0).cast(pl.Float64)
                        for s in ("MODIS_T", "MODIS_A", "VIIRS_SNPP", "VIIRS_N20", "VIIRS_N21")]))
    w = w.with_columns(
        pl.struct(["year", "week"]).map_elements(lambda r: week_days(r["year"], r["week"]),
                                                 return_dtype=pl.Int16).alias("ndays"))

    if mode == "naive":
        val = (pl.when(pl.col("source") == "VIIRS_SNPP").then(pl.col("VIIRS_SNPP") / pl.col("f_VIIRS_SNPP"))
               .when(pl.col("source") == "N20").then(pl.col("VIIRS_N20") / pl.col("f_VIIRS_N20"))
               .when(pl.col("source") == "N21").then(pl.col("VIIRS_N21") / pl.col("f_VIIRS_N21"))
               .otherwise(pl.col("MODIS_T") / pl.col("f_MODIS_T").clip(MIN_FRAC, None)
                          * (pl.col("f_MODIS_T") >= MIN_FRAC)
                          + pl.col("MODIS_A") / pl.col("f_MODIS_A").clip(MIN_FRAC, None)
                          * (pl.col("f_MODIS_A") >= MIN_FRAC)))
        w = w.with_columns(val.alias("value")).with_columns(
            pl.col("value").alias("lo"), pl.col("value").alias("hi"))
        obs = w.select("year", "week", "value")
        return ZoneData(w, [], obs, len(cells7), area)

    parts = []
    kappa, theta = st.meta["kappa"], st.meta["theta"]
    kscale = st.meta.get("kappa_scale") or {}
    n5 = float(len(np.unique(c5_of))) if len(c5_of) else 1.0

    def kap(src):
        from .harmonize.validate import kappa_for
        d = float(kappa.get(src, 1.5))
        return {"week": kappa_for(kscale.get(src), "week", n5, d), "year": kappa_for(kscale.get(src), "year", n5, d)}
    # 1. observed S-NPP weeks
    obs = (w.filter(pl.col("source") == "VIIRS_SNPP")
           .select("year", "week", (pl.col("VIIRS_SNPP") / pl.col("f_VIIRS_SNPP")).alias("value")))
    # 2. NOAA-20 / NOAA-21 weeks
    for src, sensor in (("N20", "VIIRS_N20"), ("N21", "VIIRS_N21")):
        wk = w.filter(pl.col("source") == src).select("year", "week", f"f_{sensor}")
        if wk.height == 0 or st.ratio is None or fine.height == 0:
            continue
        f = (fine.filter(pl.col("sensor") == sensor)
             .join(wk, on=["year", "week"])
             .with_columns((pl.col("week") // 4).clip(0, 12).cast(pl.Int8).alias("sbin"),
                           (pl.col("n") / pl.col(f"f_{sensor}")).alias("n_adj")))
        rt = st.ratio.filter(pl.col("src") == src)
        f = (f.join(rt.select("h3_5", "sbin", "r", "r_sd"), on=["h3_5", "sbin"], how="left")
             .with_columns(pl.col("r").fill_null(st.meta.get("viirs_global", {}).get(src, 1.0)),
                           pl.col("r_sd").fill_null(0.05)))
        if f.height == 0:
            continue
        mu = (f["n_adj"] * f["r"]).to_numpy()
        sd = (f["n_adj"] * f["r_sd"]).to_numpy()
        mem = np.maximum(np.column_stack([mu - sd, mu + sd]), 0)
        parts.append((f.select("year", "week"), mem, None, float(theta.get(src, 20)), kap(src)))
    # 3. MODIS-modelled weeks
    c5 = np.unique(c5_of)
    h = st.harm.filter(pl.col("h3_5").is_in(c5.tolist()))
    if h.height:
        mw = st.model_week.filter(pl.col("h3_5").is_in(c5.tolist())).select(
            "h3_5", "year", "week", (pl.col("n_MODIS_T") + pl.col("n_MODIS_A")).alias("Mc"))
        if fine.height:
            mp = (fine.filter(pl.col("sensor").is_in(["MODIS_T", "MODIS_A"]))
                  .group_by(["h3_5", "year", "week"]).agg(pl.col("n").sum().alias("Mz")))
        else:
            mp = pl.DataFrame(schema={"h3_5": pl.Int64, "year": pl.Int16, "week": pl.Int8, "Mz": pl.Int64})
        # Laplace share of res-7 cells without any VIIRS detection: 0.5 / (tot + 24.5)
        tot5 = st.share.group_by("h3_5").agg(pl.col("tot").first())
        sh = (pl.DataFrame({"h3_7": cells7, "h3_5": c5_of})
              .join(st.share.select("h3_7", "share"), on="h3_7", how="left")
              .join(tot5, on="h3_5", how="left")
              .with_columns(pl.col("share").fill_null(
                  pl.when(pl.col("tot").is_not_null()).then(0.5 / (pl.col("tot") + 24.5))
                  .otherwise(1.0 / 49)))
              .group_by("h3_5").agg(pl.col("share").sum().clip(0, 1).alias("sz")))
        h = (h.join(mw, on=["h3_5", "year", "week"], how="left")
             .join(mp, on=["h3_5", "year", "week"], how="left")
             .join(sh, on="h3_5", how="left")
             .with_columns(pl.col("Mc").fill_null(0), pl.col("Mz").fill_null(0), pl.col("sz").fill_null(0))
             .with_columns(pl.when(pl.col("Mc") > 0).then(pl.col("Mz") / pl.col("Mc"))
                           .otherwise(pl.col("sz")).clip(0, 1).alias("a")))
        h = h.join(w.select("year", "week", pl.col("source").alias("wsrc")), on=["year", "week"])
        h = h.filter(pl.col("wsrc") == pl.col("source"))
        for v in ("TA", "T", "A"):
            hv = h.filter(pl.col("source") == v)
            if hv.height == 0:
                continue
            mem = hv.select([f"m{b}" for b in range(st.B)]).to_numpy().astype(np.float64)
            parts.append((hv.select("year", "week"), mem, hv["a"].to_numpy(),
                          float(theta.get(v, 5)), kap(v)))
    weekly = aggregate(w.select("year", "week"), obs, parts, ["year", "week"])
    w = w.join(weekly, on=["year", "week"], how="left").with_columns(
        pl.col("value").fill_null(0.0), pl.col("lo").fill_null(0.0), pl.col("hi").fill_null(0.0))
    return ZoneData(w, parts, obs, len(cells7), area)


def aggregate(keys_all: pl.DataFrame, obs: pl.DataFrame, parts: list, by: list[str],
              keymap=None, kind: str = "week") -> pl.DataFrame:
    """Sum observed values and model parts by `by` (after optional keymap)."""
    def prep(df):
        return keymap(df) if keymap else df
    base = prep(keys_all).select(by).unique()
    o = prep(obs).group_by(by).agg(pl.col("value").sum().alias("obs"))
    out = base.join(o, on=by, how="left").with_columns(pl.col("obs").fill_null(0.0))
    mean = np.zeros(out.height); var = np.zeros(out.height)
    idx = out.select(by).with_row_index("_i")
    for keys, mem, wgt, theta, kap in parts:
        k = prep(keys).select(by).with_row_index("_r").join(idx, on=by, how="left").sort("_r")
        gi = k["_i"].to_numpy()
        ok = ~np.isnan(gi.astype(float))
        if not ok.any():
            continue
        gi = gi[ok].astype(np.int64)
        u, m, vn, vm = unc.group_sums(gi, mem[ok], None if wgt is None else wgt[ok], theta)
        mean[u] += m
        # kappa (scale- and horizon-dependent, validated) inflates the variance
        k = kap[kind] if isinstance(kap, dict) else kap
        var[u] += (vn + vm) * k ** 2
    out = out.with_columns(pl.Series("model", mean), pl.Series("var", var))
    lo, hi = unc.interval(out["model"].to_numpy(), out["var"].to_numpy(), 1.0, config.MODEL.interval)
    return out.with_columns(
        (pl.col("obs") + pl.col("model")).alias("value"),
        (pl.col("obs") + pl.Series(lo)).alias("lo"),
        (pl.col("obs") + pl.Series(hi)).alias("hi"),
    ).select(*by, "value", "lo", "hi")


# --------------------------------------------------------------------------
# Calendar & indicators
# --------------------------------------------------------------------------
def _fy(df: pl.DataFrame, sw: int) -> pl.DataFrame:
    return df.with_columns(
        pl.when(pl.col("week") >= sw).then(pl.col("year")).otherwise(pl.col("year") - 1)
        .cast(pl.Int16).alias("fyear"),
        ((pl.col("week").cast(pl.Int16) - sw) % WEEKS_PER_YEAR).cast(pl.Int8).alias("fweek"))


def week_labels(sw: int, lang: str = "fr") -> list[str]:
    months = {"fr": ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"],
              "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}[lang]
    out = []
    for fw in range(WEEKS_PER_YEAR):
        d = date(2001, 1, 1) + timedelta(days=7 * ((sw + fw) % WEEKS_PER_YEAR))
        out.append(f"{d.day} {months[d.month - 1]}")
    return out


def _r(x, nd=1):
    if x is None:
        return None
    if isinstance(x, float) and not np.isfinite(x):
        return None
    return round(float(x), nd)


def calendar(zd: ZoneData, start_week: int | str = "auto", lang: str = "fr") -> dict:
    w = zd.weekly.with_columns((7.0 / pl.col("ndays")).alias("k")).with_columns(
        (pl.col("value") * pl.col("k")).alias("v7"), (pl.col("lo") * pl.col("k")).alias("lo7"),
        (pl.col("hi") * pl.col("k")).alias("hi7"))
    clim_cal = w.group_by("week").agg(pl.col("v7").mean()).sort("week")["v7"].to_numpy()
    sw = detect_start_week(clim_cal) if start_week == "auto" else int(start_week)
    w = _fy(w, sw)
    nweeks = w.group_by("fyear").len()
    fy_all = sorted(w["fyear"].unique().to_list())
    complete = sorted(nweeks.filter(pl.col("len") == WEEKS_PER_YEAR)["fyear"].to_list())
    current = fy_all[-1] if fy_all and fy_all[-1] not in complete else None

    # fire-year x week matrix
    W = WEEKS_PER_YEAR
    mat = {fy: np.full(W, np.nan) for fy in fy_all}
    lo = {fy: np.full(W, np.nan) for fy in fy_all}
    hi = {fy: np.full(W, np.nan) for fy in fy_all}
    src = {fy: [None] * W for fy in fy_all}
    for r in w.select("fyear", "fweek", "v7", "lo7", "hi7", "source").iter_rows():
        fy, fw, v, l, h_, s = r
        mat[fy][fw], lo[fy][fw], hi[fy][fw], src[fy][fw] = v, l, h_, s

    # annual totals with proper uncertainty (members summed over the fire year)
    def km(df):
        return _fy(df, sw)
    tot = aggregate(zd.weekly.select("year", "week"), zd.obs, zd.parts, ["fyear"], keymap=km, kind="year")
    totd = {r["fyear"]: r for r in tot.to_dicts()}

    hist = [fy for fy in complete]
    X = np.array([mat[fy] for fy in hist]) if hist else np.zeros((0, W))
    clim = {}
    if len(hist):
        for q in (10, 25, 50, 75, 90):
            clim[f"p{q}"] = [_r(v) for v in np.nanpercentile(X, q, axis=0)]
        clim["mean"] = [_r(v) for v in np.nanmean(X, axis=0)]
    mean_clim = np.nanmean(X, axis=0) if len(hist) else np.zeros(W)

    years = []
    dates = {}
    for fy in fy_all:
        sd = indicators.season_dates(mat[fy]) if fy in complete else {}
        dates[fy] = sd
        t = totd.get(fy, {})
        srcs = [s for s in src[fy] if s]
        main = max(set(srcs), key=srcs.count) if srcs else None
        years.append({
            "fyear": fy, "label": f"{fy}-{str(fy + 1)[-2:]}" if sw else str(fy),
            "complete": fy in complete, "current": fy == current,
            "weeks": [_r(v) for v in mat[fy]], "lo": [_r(v) for v in lo[fy]],
            "hi": [_r(v) for v in hi[fy]], "source": src[fy], "main_source": main,
            "total": _r(t.get("value")), "total_lo": _r(t.get("lo")), "total_hi": _r(t.get("hi")),
            "onset": sd.get("onset"), "peak": sd.get("peak"), "end": sd.get("end"),
            "duration": sd.get("duration")})

    # trends over complete years
    trends = {}
    if len(hist) >= 6:
        for k in ("onset", "peak", "end", "duration"):
            trends[k] = indicators.trend(hist, [dates[fy].get(k) for fy in hist])
        tots = [totd.get(fy, {}).get("value") for fy in hist]
        tl = indicators.trend(hist, [np.log(t) if t and t > 0 else None for t in tots])
        if tl:
            tl["pct_per_decade"] = float(100 * (np.exp(tl["slope"]) - 1))
            tl["pct_lo"] = float(100 * (np.exp(tl["lo"]) - 1))
            tl["pct_hi"] = float(100 * (np.exp(tl["hi"]) - 1))
        trends["total"] = tl

    # season summary (medians) and critical windows
    def med(k):
        v = [dates[fy].get(k) for fy in hist if dates[fy].get(k) is not None]
        return int(np.median(v)) if v else None
    summary = {k: med(k) for k in ("onset", "peak", "end", "duration")}
    crit = {f"{int(s * 100)}": indicators.critical_window(mean_clim, s) for s in SEASON.critical_share}

    # anomalies
    thr = 0.05 * np.nanmax(mean_clim) if np.isfinite(np.nanmax(mean_clim)) and np.nanmax(mean_clim) > 0 else 0
    wk_anom = []
    for i, fy in enumerate(hist):
        others = [j for j in range(len(hist)) if j != i]
        for fw in range(W):
            if mean_clim[fw] < thr or not np.isfinite(mat[fy][fw]):
                continue
            ref = X[others][:, max(0, fw - 1):fw + 2].ravel()
            p = indicators.empirical_percentile(mat[fy][fw], ref)
            if p is not None and (p >= SEASON.anomaly_hi or p <= SEASON.anomaly_lo):
                wk_anom.append({"fyear": fy, "fweek": fw, "value": _r(mat[fy][fw]), "pct": _r(p),
                                "ratio": _r(mat[fy][fw] / mean_clim[fw], 2) if mean_clim[fw] else None})
    wk_anom.sort(key=lambda a: -abs((a["ratio"] or 1) - 1))
    yr_anom = []
    tots = np.array([totd.get(fy, {}).get("value") or np.nan for fy in hist])
    on_med = summary.get("onset")
    for i, fy in enumerate(hist):
        ref = np.delete(tots, i)
        p = indicators.empirical_percentile(tots[i], ref)
        lt = np.log(np.maximum(tots, 1e-9))
        z = (lt[i] - np.nanmean(np.delete(lt, i))) / (np.nanstd(np.delete(lt, i)) or 1)
        on = dates[fy].get("onset")
        flag = []
        if p is not None and p >= SEASON.anomaly_hi:
            flag.append("high")
        if p is not None and p <= SEASON.anomaly_lo:
            flag.append("low")
        if on is not None and on_med is not None and on - on_med <= -3:
            flag.append("early")
        if on is not None and on_med is not None and on - on_med >= 3:
            flag.append("late")
        yr_anom.append({"fyear": fy, "total": _r(tots[i]), "pct": _r(p), "z": _r(z, 2),
                        "onset_shift": (on - on_med) if (on is not None and on_med is not None) else None,
                        "flags": flag})

    # current season status
    cur = None
    if current is not None:
        vals = mat[current]
        avail = [fw for fw in range(W) if np.isfinite(vals[fw])]
        weeks_status = []
        cum = 0.0
        cum_hist = np.nancumsum(X, axis=1) if len(hist) else None
        for fw in avail:
            ref = X[:, max(0, fw - 1):fw + 2].ravel() if len(hist) else np.array([])
            p = indicators.empirical_percentile(vals[fw], ref)
            cum += vals[fw]
            weeks_status.append({"fweek": fw, "value": _r(vals[fw]), "pct": _r(p),
                                 "status": indicators.status_label(p) if mean_clim[fw] >= thr else "offseason",
                                 "source": src[current][fw]})
        last = avail[-1] if avail else None
        cum_p = (indicators.empirical_percentile(cum, cum_hist[:, last]) if last is not None and cum_hist is not None
                 else None)
        cum_med = float(np.nanmedian(cum_hist[:, last])) if last is not None and cum_hist is not None else 0.0
        few = cum_med < 10  # percentiles of near-empty histories are meaningless
        if few:
            for ws in weeks_status:
                ws["status"] = "few"
        cur = {"fyear": current, "label": f"{current}-{str(current + 1)[-2:]}", "weeks": weeks_status,
               "last_fweek": last, "cumulative": _r(cum), "cumulative_pct": _r(cum_p),
               "cumulative_status": "few" if few else indicators.status_label(cum_p),
               "last_status": weeks_status[-1] if weeks_status else None,
               "clim_cum_median": _r(float(np.nanmedian(cum_hist[:, last]))) if last is not None and cum_hist is not None else None}

    return {"start_week": sw, "week_labels": week_labels(sw, lang), "years": years,
            "complete_years": complete, "current": cur, "climatology": clim,
            "summary": summary, "critical": crit, "trends": trends,
            "anomalies": {"weeks": wk_anom[:40], "years": yr_anom},
            "cells": zd.cells7, "area_km2": _r(zd.area_km2, 0)}


def sensors_series(zd: ZoneData) -> dict:
    w = zd.weekly
    out = (w.group_by("year").agg(*[pl.col(s).sum() for s in
                                    ("MODIS_T", "MODIS_A", "VIIRS_SNPP", "VIIRS_N20", "VIIRS_N21")],
                                  pl.col("value").sum().alias("harmonized"))
           .sort("year"))
    return {"annual": out.to_dicts()}


def weekly_csv(zd: ZoneData, sw: int) -> str:
    w = _fy(zd.weekly, sw).with_columns(
        pl.struct(["year", "week"]).map_elements(
            lambda r: (date(r["year"], 1, 1) + timedelta(days=7 * r["week"])).isoformat(),
            return_dtype=pl.Utf8).alias("week_start"))
    cols = ["week_start", "year", "week", "fyear", "fweek", "source", "value", "lo", "hi", "ndays",
            "MODIS_T", "MODIS_A", "VIIRS_SNPP", "VIIRS_N20", "VIIRS_N21"]
    return w.select(cols).sort(["year", "week"]).write_csv()
