"""Unit tests for the parts that do not need the downloaded archives."""
import numpy as np
import polars as pl
import pytest

from firesync import indicators
from firesync.api import auth
from firesync.harmonize import uncertainty as unc
from firesync.harmonize.validate import kappa_for
from firesync.processing import week_days
from firesync.seasonal import add_fire_year, detect_start_week, fire_week_start


def gaussian_season(peak=15, width=4, total=1000):
    x = np.arange(52)
    w = np.exp(-0.5 * ((x - peak) / width) ** 2)
    return total * w / w.sum()


def test_week_days_sum_to_year():
    assert sum(week_days(2023, w) for w in range(52)) == 365
    assert sum(week_days(2024, w) for w in range(52)) == 366


def test_fire_year_assignment():
    df = pl.DataFrame({"year": [2020, 2020, 2021], "week": [35, 36, 10]})
    out = add_fire_year(df, 36)
    assert out["fyear"].to_list() == [2019, 2020, 2020]
    assert out["fweek"].to_list() == [51, 0, 26]
    assert fire_week_start(2020, 0, 36).isoformat() == "2020-09-09"  # 2020 is a leap year
    assert fire_week_start(2020, 20, 36).isoformat() == "2021-01-29"


def test_detect_start_week_is_minimum():
    clim = gaussian_season(peak=5, width=6) + 1
    clim = np.roll(clim, 40)  # peak around week 45
    sw = detect_start_week(clim)
    assert clim[sw] <= np.percentile(clim, 10)


def test_season_dates():
    x = gaussian_season(peak=20, width=3)
    d = indicators.season_dates(x)
    assert d["peak"] == 20
    assert d["onset"] < 20 < d["end"]
    assert d["duration"] == d["end"] - d["onset"] + 1
    assert indicators.season_dates(np.zeros(52))["onset"] is None


def test_critical_window_contains_share():
    x = gaussian_season(peak=26, width=5)
    c = indicators.critical_window(x, 0.5)
    assert c["share"] >= 0.5 and c["start"] <= 26 <= c["end"]
    assert c["weeks"] < indicators.critical_window(x, 0.8)["weeks"]


def test_percentile_and_status():
    ref = np.arange(1, 101)
    assert indicators.empirical_percentile(95.5, ref) == pytest.approx(95.0)
    assert indicators.status_label(95) == "above_p90"
    assert indicators.status_label(50) == "normal"
    assert indicators.status_label(5) == "below_p10"


def test_trend_detects_slope():
    yrs = list(range(2000, 2025))
    tr = indicators.trend(yrs, [0.5 * (y - 2000) for y in yrs])
    assert tr["slope"] == pytest.approx(5.0) and tr["significant"]


def test_interval_monotone_in_kappa_and_handles_zero():
    m, v = np.array([0.0, 2.0, 50.0]), np.array([0.0, 6.0, 900.0])
    lo1, hi1 = unc.interval(m, v, 1.0)
    lo2, hi2 = unc.interval(m, v, 2.0)
    assert hi1[0] == 0 and lo1[0] == 0
    assert np.all(hi2 >= hi1) and np.all(lo2 <= lo1)
    assert np.all(lo1 >= 0)


def test_calibrated_kappa_reaches_coverage():
    rng = np.random.default_rng(0)
    mean = rng.uniform(5, 200, 4000)
    obs = rng.negative_binomial(3, 3 / (3 + mean))
    var_too_small = mean + mean ** 2 / 12  # half the true excess variance
    k = unc.calibrate_kappa(obs, mean, var_too_small)
    assert k > 1
    assert unc.coverage(obs, mean, var_too_small, k) >= 0.9


def test_group_sums_member_variance():
    g = np.array([0, 0, 1])
    mem = np.array([[1.0, 3.0], [1.0, 3.0], [5.0, 5.0]])
    u, mean, vn, vm = unc.group_sums(g, mem, None, theta=1e9)
    assert mean.tolist() == [4.0, 5.0]
    assert vm[0] == pytest.approx(8.0) and vm[1] == 0


def test_kappa_interpolation_monotone():
    ks = {"week": [{"cells": 1, "kappa": 1.3}, {"cells": 30, "kappa": 1.2}, {"cells": 900, "kappa": 2.5}]}
    assert kappa_for(ks, "week", 30, 9) == pytest.approx(1.3)  # never below a smaller scale
    assert 1.3 < kappa_for(ks, "week", 200, 9) < 2.5
    assert kappa_for(None, "week", 10, 1.7) == 1.7


def test_password_hash_and_token():
    h = auth.hash_password("correct horse")
    assert auth.verify_password("correct horse", h) and not auth.verify_password("nope", h)
    tok = auth.make_token(7, "pro")
    assert auth.read_token(tok)["uid"] == 7
    assert auth.read_token(tok[:-2] + "xx") is None
