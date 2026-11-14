import numpy as np

from firesync import forecast


def test_prob_above_monotone():
    thr = np.array([50.0])
    p_low = forecast.prob_above(np.array([20.0]), np.array([60.0]), thr)[0]
    p_mid = forecast.prob_above(np.array([50.0]), np.array([150.0]), thr)[0]
    p_high = forecast.prob_above(np.array([120.0]), np.array([400.0]), thr)[0]
    assert 0 <= p_low < p_mid < p_high <= 1


def test_risk_levels():
    assert forecast.risk(1, 1, 0.9, 3) == "offseason"
    assert forecast.risk(200, 100, 0.7, 2.0) == "high"
    assert forecast.risk(120, 100, 0.4, 1.2) == "moderate"
    assert forecast.risk(90, 100, 0.2, 0.9) == "low"
    # a few fires against a near-zero normal is not an alert, whatever the ratio
    assert forecast.risk(5.5, 1.0, 0.57, 3.3) == "offseason"
    # a big ratio needs a material excess of fires to be "high"
    assert forecast.risk(33.6, 19.5, 0.39, 1.68) == "moderate"
    assert forecast.risk(234.8, 135.8, 0.23, 1.72) == "high"
    # large zone near normal: normal, not "low risk"
    assert forecast.risk(1702, 1601, 0.27, 1.06) == "low"
    # well below a large normal: still "normal or below", not "low activity"
    assert forecast.risk(6, 40, 0.05, 0.17) == "low"


def test_platt_fixes_overconfidence():
    rng = np.random.default_rng(0)
    true_p = rng.uniform(0.05, 0.6, 20000)
    ev = rng.random(true_p.size) < true_p
    # overconfident forecaster: pushes probabilities away from 0.5
    lg = np.log(true_p / (1 - true_p)) * 1.8 + 0.3
    p_over = 1 / (1 + np.exp(-lg))
    ab = forecast.platt_fit(p_over, ev)
    p_cal = forecast.platt_apply(p_over, ab)
    brier = lambda p: np.mean((p - ev) ** 2)
    assert brier(p_cal) < brier(p_over)
    assert 0.4 < ab[0] < 0.75  # slope ~ 1/1.8
    assert np.all(np.diff(p_cal[np.argsort(p_over)]) >= -1e-12)  # monotone


def test_alert_message_is_sms_sized():
    z = {"issue": {"targets": [{"start": "2026-11-12"}, {"start": "2026-11-19"}]},
         "next2": {"mu": 431.6, "ratio": 1.62, "risk": "high"}}
    for lang in ("fr", "en"):
        msg = forecast.alert_message("Kédougou", z, lang)
        assert "Kédougou" in msg and len(msg) <= 200
    assert "ÉLEVÉ" in forecast.alert_message("X", z, "fr")
