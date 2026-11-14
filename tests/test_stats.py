"""firesync.stats must match scipy.stats (scipy is only installed with the pipeline)."""
import numpy as np
import pytest

from firesync import stats

sp = pytest.importorskip("scipy.stats")


def test_norm():
    x = np.linspace(-6, 6, 241)
    assert np.allclose(stats.norm_cdf(x), sp.norm.cdf(x), atol=1e-12)
    for p in (0.025, 0.05, 0.5, 0.95, 0.975):
        assert abs(stats.norm_ppf(p) - sp.norm.ppf(p)) < 1e-9


@pytest.mark.parametrize("seed", range(40))
def test_theilsen_and_kendall_match_scipy(seed):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(6, 40))
    years = np.arange(2000, 2000 + n, dtype=float)
    vals = rng.gamma(2.0, 500.0, n) + seed * 3 * np.arange(n)
    if seed % 5 == 0:  # ties in the values
        vals = np.round(vals / 400.0) * 400.0
    s, i, lo, hi = stats.theilslopes(vals, years)
    r = sp.theilslopes(vals, years)
    assert np.allclose([s, i, lo, hi], [r.slope, r.intercept, r.low_slope, r.high_slope], equal_nan=True)
    tau, p = stats.kendalltau(years, vals)
    k = sp.kendalltau(years, vals)
    assert abs(tau - k.statistic) < 1e-12 and abs(p - k.pvalue) < 1e-9
