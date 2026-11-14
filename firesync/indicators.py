"""Season indicators computed on a fire-year x week matrix."""
from __future__ import annotations

import numpy as np
from .stats import kendalltau, theilslopes  # numpy versions of scipy.stats (lean web bundle)

from .config import SEASON


def smooth3(x: np.ndarray) -> np.ndarray:
    x = np.nan_to_num(np.asarray(x, dtype=float))
    p = np.pad(x, 1, mode="edge")
    return (p[:-2] + p[1:-1] + p[2:]) / 3.0


def season_dates(x: np.ndarray, onset_q: float = SEASON.onset_q, end_q: float = SEASON.end_q,
                 min_total: float = 1.0) -> dict:
    """Onset / peak / end (0-based fire weeks) from cumulative activity."""
    x = np.nan_to_num(np.asarray(x, dtype=float))
    tot = float(x.sum())
    if tot < min_total:
        return {"onset": None, "peak": None, "end": None, "duration": None, "total": tot}
    cum = np.cumsum(x) / tot
    onset = int(np.argmax(cum >= onset_q))
    end = int(np.argmax(cum >= end_q))
    peak = int(np.argmax(smooth3(x)))
    return {"onset": onset, "peak": peak, "end": end, "duration": end - onset + 1, "total": tot}


def critical_window(clim: np.ndarray, share: float) -> dict | None:
    """Shortest contiguous run of weeks holding at least `share` of activity."""
    x = np.nan_to_num(np.asarray(clim, dtype=float))
    tot = x.sum()
    if tot <= 0:
        return None
    n = len(x)
    best = None
    cs = np.concatenate([[0.0], np.cumsum(x)])
    j = 0
    for i in range(n):
        j = max(j, i)
        while j < n and cs[j + 1] - cs[i] < share * tot:
            j += 1
        if j >= n:
            break
        if best is None or (j - i) < (best[1] - best[0]):
            best = (i, j)
    if best is None:
        return None
    i, j = best
    return {"start": int(i), "end": int(j), "weeks": int(j - i + 1),
            "share": float((cs[j + 1] - cs[i]) / tot)}


def empirical_percentile(v: float, ref: np.ndarray) -> float | None:
    ref = np.asarray(ref, dtype=float)
    ref = ref[np.isfinite(ref)]
    if ref.size == 0 or v is None or not np.isfinite(v):
        return None
    return float(100.0 * (np.sum(ref < v) + 0.5 * np.sum(ref == v)) / ref.size)


def trend(years, values, per: int = 10) -> dict | None:
    """Theil-Sen slope (units per `per` years) with Mann-Kendall p-value."""
    y = np.asarray(years, dtype=float)
    v = np.asarray([np.nan if x is None else x for x in values], dtype=float)
    m = np.isfinite(v)
    if m.sum() < 6:
        return None
    s, icpt, lo, hi = theilslopes(v[m], y[m])
    tau, p = kendalltau(y[m], v[m])
    return {"slope": float(s * per), "lo": float(lo * per), "hi": float(hi * per),
            "intercept": float(icpt), "tau": float(tau), "p": float(p), "n": int(m.sum()),
            "significant": bool(p < 0.05)}


def status_label(pct: float | None) -> str:
    if pct is None:
        return "nodata"
    if pct >= 90:
        return "above_p90"
    if pct >= 75:
        return "p75_p90"
    if pct > 25:
        return "normal"
    if pct > 10:
        return "p10_p25"
    return "below_p10"
