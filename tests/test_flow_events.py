"""experiments/flow_events.py: the event rule, per-point scaling, the placebo and the premium curve (synthetic data)."""

import numpy as np
import pandas as pd
import pytest

import flow_events as fe

DAYS = pd.date_range("2019-01-01", "2022-12-31", freq="D")
BDAYS = pd.bdate_range("2019-01-01", "2026-12-31")


def share(level=1.0, drops=()):
    """A flat daily flow share with (start, days, level) drops."""
    s = pd.Series(level, index=DAYS)
    for start, days, low in drops:
        s.loc[pd.Timestamp(start):pd.Timestamp(start) + pd.Timedelta(days=days - 1)] = low
    return s


def test_rule_finds_sustained_drops_once_per_episode():
    s = share(drops=[("2019-06-01", 30, 0.6),   # sustained: an event
                     ("2019-09-01", 30, 0.6),   # sustained, but within GAP of the first
                     ("2020-03-01", 10, 0.4),   # deep but too short
                     ("2020-08-01", 40, 0.8),   # sustained but too shallow (20 points)
                     ("2021-06-01", 60, 0.5)])  # half a year on: a new event
    assert fe.find_events(s, "2019-02-01", "2022-06-30") == [pd.Timestamp("2019-06-01"), pd.Timestamp("2021-06-01")]
    # the search window applies to the event's day 0
    assert fe.find_events(s, "2019-07-01", "2022-06-30") == [pd.Timestamp("2019-09-01"), pd.Timestamp("2021-06-01")]


def test_rule_ignores_a_slow_drift():
    s = pd.Series(np.interp(np.arange(len(DAYS)), [0, 400, 520, len(DAYS)], [1.0, 1.0, 0.6, 0.6]), index=DAYS)
    assert fe.find_events(s, "2019-02-01", "2022-06-30") == []  # 40 points, but over four months
    assert fe.find_events(s, "2019-02-01", "2022-06-30", drop=0.05) != []


def test_rule_uses_the_pre_level_not_normal():
    # Flow already at 70% of normal falls to 40%: 30 points below its own pre-level, an event.
    s = share(level=0.7, drops=[("2020-02-01", 30, 0.4)])
    assert fe.find_events(s, "2019-02-01", "2022-06-30") == [pd.Timestamp("2020-02-01")]
    assert fe.pre_level(s).loc["2020-02-01"] == pytest.approx(0.7)


def test_shortfall_and_per_point_scaling():
    s = share(drops=[("2020-02-01", 60, 0.6)])
    assert fe.shortfall(s, "2020-02-01", "2020-02-20") == pytest.approx(40)
    assert fe.shortfall(s, "2020-02-01", "2020-04-30") == pytest.approx(40 * 60 / 90)  # recovered after 60 days
    # Brent with a known premium of 0.004 log points per point of lost flow from day 0.
    i0, lost, e = 300, 40.0, 0.004
    brent = pd.Series(50.0, index=BDAYS)
    brent.iloc[i0:] = 50.0 * np.exp(e * lost)
    m = fe.moves(brent, i0, (5, 20))
    np.testing.assert_allclose(m, e * lost)
    assert fe.per_point(m[0], lost) == pytest.approx(100 * e)  # % of Brent per point
    assert fe.per_point(m[0], 2 * lost) == pytest.approx(50 * e)
    assert np.isnan(fe.per_point(m[0], fe.MIN_LOST / 2))
    assert np.isnan(fe.moves(brent, len(brent) - 3, (5,))[0])  # past the end of the data


def test_placebo_excludes_events_and_stops_before_the_closure():
    rng = np.random.default_rng(0)
    sigma = 0.02
    brent = pd.Series(60 * np.exp(np.cumsum(rng.normal(0, sigma, len(BDAYS)))), index=BDAYS)
    ev = fe.day0(brent, "2022-06-01")
    horizons = (5, 20)
    noise = fe.placebo(brent, [ev], lo="2019-02-01", hi="2026-02-01", horizons=horizons)
    first, last = fe.day0(brent, "2019-02-01"), fe.day0(brent, "2026-02-01") - max(horizons)
    assert len(noise) == (last - first) - (2 * fe.EXCLUDE + 1)
    # each placebo move spans h + BASE_LAG days of a random walk
    for k, h in enumerate(horizons):
        sd = sigma * np.sqrt(h + fe.BASE_LAG)
        assert np.quantile(noise[:, k], 0.95) == pytest.approx(1.645 * sd, rel=0.15)
    # the band is in % per point and shrinks with the event's lost flow
    lo, hi = fe.placebo_band(noise[:, 1], 20.0)
    lo2, hi2 = fe.placebo_band(noise[:, 1], 40.0)
    assert lo < 0 < hi and (lo, hi) == pytest.approx((2 * lo2, 2 * hi2))
    assert np.isnan(fe.placebo_band(noise[:, 1], 1.0)[0])


def test_placebo_on_a_true_premium_rejects_it():
    # An event that adds a 25% jump stands far outside the placebo of a quiet random walk.
    rng = np.random.default_rng(1)
    logp = np.cumsum(rng.normal(0, 0.01, len(BDAYS)))
    i0 = fe.day0(pd.Series(0, index=BDAYS), "2023-03-01")
    logp[i0:] += 0.25
    brent = pd.Series(np.exp(logp), index=BDAYS)
    noise = fe.placebo(brent, [i0], horizons=fe.HORIZONS)
    m = fe.moves(brent, i0)
    assert (noise[:, 1] >= m[1]).mean() < 0.01


def test_news_match_window():
    t0 = pd.Timestamp("2024-01-01")
    assert "Galaxy Leader" in fe.news_for(fe.BABEL, t0)  # 2023-11-19 is 43 days before
    assert fe.news_for(fe.BABEL, pd.Timestamp("2024-03-01")) == ""
    assert fe.news_for(fe.HORMUZ, t0) == ""


def test_bypass_offset():
    gulf = pd.Series(1.0, index=DAYS)
    byp = pd.Series(0.2, index=DAYS)
    gulf.loc["2020-03-01":] = 0.2  # 0.8 lost
    byp.loc["2020-03-01":] = 0.6  # 0.4 gained
    assert fe.bypass_offset(byp, gulf, "2020-03-01", "2020-05-01") == pytest.approx(0.5)
    byp.loc["2020-06-01":] = 0.1  # the bypass ports themselves fall below their pre-level
    assert fe.bypass_offset(byp, gulf, "2020-03-01", "2020-07-01", a="2020-06-01") == pytest.approx(-0.125)


def test_fit_curve_recovers_a_known_shape():
    d = np.arange(1, 151, dtype=float)
    truth = dict(jump=0.002, peak=0.007, d_peak=20, half_life=15.0, plateau=0.003)
    y = fe.curve_shape(d, **truth) + np.random.default_rng(2).normal(0, 1e-5, len(d))
    p = fe.fit_curve(y)
    assert p["d_peak"] == truth["d_peak"] and p["half_life"] == truth["half_life"]
    for key in ("jump", "peak", "plateau"):
        assert p[key] == pytest.approx(truth[key], abs=2e-5)
    assert fe.curve_shape(np.array([20.0]), **truth)[0] == pytest.approx(truth["peak"])


def test_premium_curve_band_and_extrapolation():
    rng = np.random.default_rng(3)
    obs, days, lost = 120, 200, 80.0
    d = np.arange(1, obs + 1, dtype=float)
    y = fe.curve_shape(d, 0.002, 0.006, 20, 10.0, 0.003) + rng.normal(0, 3e-4, obs)
    walk = np.cumsum(rng.normal(0, 0.02, (500, days + 5)), axis=1)
    noise = walk[:, 5:] - walk[:, :1]  # moves at horizons 1..days, like placebo()
    curve, p = fe.premium_curve(y, noise, lost, days=days)
    assert list(curve["trading_day"]) == list(range(1, days + 1))
    assert (curve["e_low"] >= 0).all()
    assert (curve["e_low"] <= curve["e_mid"]).all() and (curve["e_mid"] <= curve["e_high"]).all()
    assert curve["observed"].sum() == obs
    after = curve.loc[~curve["observed"], "e_mid"].to_numpy()
    assert (after == curve["e_mid"].iloc[obs - 1]).all()  # held at the last observed day's value
    assert after[0] == pytest.approx(p["plateau"], rel=1e-2)  # which is the plateau once the decay is done
    width = (curve["e_high"] - curve["e_mid"]).to_numpy()
    assert width[-1] > 2 * width[9]  # the band widens with the horizon
    # the band is the noise of one event: halving the event's lost flow doubles its half-width
    curve2, _ = fe.premium_curve(y * 2, noise, lost / 2, days=days)
    np.testing.assert_allclose(curve2["e_high"] - curve2["e_mid"], 2 * (curve["e_high"] - curve["e_mid"]), rtol=1e-9)


def test_chain_premium_is_the_current_oil_paths_shape():
    c = fe.chain_premium()
    assert c[fe.OP_D_PEAK - 1] == pytest.approx(fe.OP_E_PEAK)
    assert c[fe.OP_D_LATE - 1] == pytest.approx(fe.OP_E_LATE)
    assert c[-1] == pytest.approx(fe.OP_E_LATE) and len(c) == fe.CURVE_DAYS
