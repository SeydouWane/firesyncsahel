"""Small statistics needed by the web platform, in numpy only.

They reproduce scipy.stats exactly (same formulas, same small-sample rules) so
that the serving bundle does not need scipy (~120 MB); scipy remains a
dependency of the data pipeline. tests/test_stats.py checks the equivalence.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

_N01 = NormalDist()
_erfc = np.frompyfunc(math.erfc, 1, 1)


def norm_cdf(x):
    """Standard normal CDF (vectorised) — scipy.stats.norm.cdf."""
    x = np.asarray(x, dtype=float)
    out = np.asarray(_erfc(-x / math.sqrt(2.0)), dtype=float) * 0.5
    return out if out.ndim else float(out)


def norm_ppf(p: float) -> float:
    """Standard normal quantile (scalar) — scipy.stats.norm.ppf."""
    return _N01.inv_cdf(float(p))


def _repeat_counts(a: np.ndarray) -> np.ndarray:
    _, c = np.unique(a, return_counts=True)
    return c[c > 1]


def theilslopes(y, x, alpha: float = 0.95):
    """Theil–Sen slope with Sen (1968) confidence bounds — scipy.stats.theilslopes
    (method='separate'). Returns (slope, intercept, low_slope, high_slope)."""
    y = np.asarray(y, dtype=float).ravel()
    x = np.asarray(x, dtype=float).ravel()
    dx = x[:, None] - x
    dy = y[:, None] - y
    pos = dx > 0
    slopes = np.sort(dy[pos] / dx[pos])
    if not slopes.size:
        raise ValueError("all x coordinates are identical")
    med = float(np.median(slopes))
    icpt = float(np.median(y) - med * np.median(x))
    if alpha > 0.5:
        alpha = 1.0 - alpha
    z = norm_ppf(alpha / 2.0)
    nt, ny = len(slopes), len(y)
    sigsq = (ny * (ny - 1) * (2 * ny + 5)
             - sum(k * (k - 1) * (2 * k + 5) for k in _repeat_counts(x))
             - sum(k * (k - 1) * (2 * k + 5) for k in _repeat_counts(y))) / 18.0
    try:
        sigma = math.sqrt(sigsq)
        ru = min(int(np.round((nt - z * sigma) / 2.0)), nt - 1)
        rl = max(int(np.round((nt + z * sigma) / 2.0)) - 1, 0)
        lo, hi = float(slopes[rl]), float(slopes[ru])
    except (ValueError, IndexError):
        lo, hi = float("nan"), float("nan")
    return med, icpt, lo, hi


def _kendall_p_exact(n: int, c: int) -> float:
    """Two-sided exact p-value of Kendall's tau without ties (Kendall 1970)."""
    c = int(min(c, n * (n - 1) // 2 - c))
    if n <= 2:
        return 1.0
    if c == 0:
        return min(2.0 / math.factorial(n), 1.0)
    if c == 1:
        return min(2.0 / math.factorial(n - 1), 1.0)
    if 4 * c == n * (n - 1):
        return 1.0
    new = np.zeros(c + 1)
    new[0:2] = 1.0
    for j in range(3, n + 1):
        new = np.cumsum(new)
        if j <= c:
            new[j:] -= new[:c + 1 - j]
    return min(2.0 * float(np.sum(new)) / math.factorial(n), 1.0)


def kendalltau(x, y):
    """Kendall's tau-b and two-sided p-value — scipy.stats.kendalltau(method='auto'):
    exact distribution without ties for n <= 33, normal approximation otherwise."""
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    n = x.size
    iu = np.triu_indices(n, 1)
    s = (np.sign(x[:, None] - x[None, :]) * np.sign(y[:, None] - y[None, :]))[iu]
    con, dis = int((s > 0).sum()), int((s < 0).sum())
    tot = n * (n - 1) // 2

    def ties(a):
        c = _repeat_counts(a).astype(float)
        return int((c * (c - 1) // 2).sum()), float((c * (c - 1) * (c - 2)).sum()), float((c * (c - 1) * (2 * c + 5)).sum())

    xtie, x0, x1 = ties(x)
    ytie, y0, y1 = ties(y)
    if xtie == tot or ytie == tot:
        return float("nan"), float("nan")
    cmd = con - dis
    tau = float(np.clip(cmd / math.sqrt(tot - xtie) / math.sqrt(tot - ytie), -1.0, 1.0))
    if xtie == 0 and ytie == 0 and (n <= 33 or min(dis, tot - dis) <= 1):
        p = _kendall_p_exact(n, tot - dis)
    else:
        m = n * (n - 1.0)
        var = ((m * (2 * n + 5) - x1 - y1) / 18.0 + (2.0 * xtie * ytie) / m + x0 * y0 / (9.0 * m * (n - 2)))
        z = cmd / math.sqrt(var)
        p = float(2.0 * norm_cdf(-abs(z)))
    return tau, p
