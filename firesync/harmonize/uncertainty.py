"""Predictive uncertainty of harmonised counts aggregated over any zone.

For a zone and a week the harmonised value is a weighted sum over model cells,
H = sum_c a_c * V_c, where a_c in [0, 1] is the share of cell c inside the zone.

Two variance components:
* model (parameter) uncertainty — taken from the ensemble members: the member
  sums sum_c a_c * mu_{c,b} carry the full spatial/temporal correlation of the
  model error, so var_model = Var_b( sum_c a_c mu_{c,b} );
* sampling noise of the counts — negative binomial with dispersion theta:
  var_noise = sum_c a_c mu_c + a_c^2 mu_c^2 / theta.

The total variance is inflated by kappa^2, a calibration factor estimated on
held-out years so that the nominal 90 % intervals contain 90 % of the
observations (validated, not assumed). Intervals use a gamma distribution
with the same mean and variance (positive, skewed like counts), rounded
outwards to integers.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import gamma


def nb_theta(y: np.ndarray, mu: np.ndarray) -> float:
    """Method-of-moments NB dispersion: Var = mu + mu^2/theta."""
    m = mu > 0.05
    excess = np.sum((y[m] - mu[m]) ** 2 - mu[m])
    if excess <= 0:
        return 1e6
    return float(np.sum(mu[m] ** 2) / excess)


def group_sums(group: np.ndarray, members: np.ndarray, weight: np.ndarray | None,
               theta: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (unique groups, mean, var_noise, var_model) of weighted sums."""
    w = np.ones(len(group)) if weight is None else weight
    uniq, inv = np.unique(group, return_inverse=True)
    G, B = len(uniq), members.shape[1]
    msum = np.zeros((G, B))
    for b in range(B):
        msum[:, b] = np.bincount(inv, weights=w * members[:, b], minlength=G)
    mu = members.mean(axis=1)
    vn = np.bincount(inv, weights=w * mu + (w * mu) ** 2 / theta, minlength=G)
    mean = msum.mean(axis=1)
    vm = msum.var(axis=1, ddof=1) if B > 1 else np.zeros(G)
    return uniq, mean, vn, vm


def interval(mean: np.ndarray, var: np.ndarray, kappa: float = 1.0, level: float = 0.9
             ) -> tuple[np.ndarray, np.ndarray]:
    """Central interval for a count with the given mean and variance.

    log(X + 1) is taken as Gaussian with moments matched to (mean, var); kappa
    multiplies its standard deviation. Unlike a heavily inflated negative
    binomial (whose upper quantile collapses to 0 when the variance explodes),
    the width grows monotonically with kappa, so the calibration is well posed.
    Bounds are rounded outwards to integers and never negative.
    """
    from scipy.stats import norm
    m = np.maximum(np.asarray(mean, dtype=float), 0.0)
    v = np.maximum(np.asarray(var, dtype=float), m)  # at least Poisson
    s2 = np.log1p(v / (m + 1.0) ** 2)
    mu = np.log(m + 1.0) - s2 / 2
    z = norm.ppf(0.5 + level / 2) * kappa
    s = np.sqrt(s2)
    lo = np.floor(np.maximum(np.exp(mu - z * s) - 1.0, 0.0))
    hi = np.ceil(np.exp(mu + z * s) - 1.0)
    zero = m <= 1e-9
    lo[zero] = 0.0
    hi[zero] = 0.0
    return lo, hi


def coverage(obs, mean, var, kappa: float, level: float = 0.9) -> float:
    lo, hi = interval(mean, var, kappa, level)
    return float(np.mean((obs >= lo) & (obs <= hi)))


def calibrate_kappa(obs, mean, var, level: float = 0.9, lo: float = 0.2, hi: float = 6.0) -> float:
    """Smallest kappa whose empirical coverage reaches the nominal level."""
    obs, mean, var = map(np.asarray, (obs, mean, var))
    if coverage(obs, mean, var, hi, level) < level:
        return hi
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if coverage(obs, mean, var, mid, level) >= level:
            hi = mid
        else:
            lo = mid
    return float(hi)
