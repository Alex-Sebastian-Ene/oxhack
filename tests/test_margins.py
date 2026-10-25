"""experiments/margins.py: the crack identity and splice, the margin equation's fit (normal months
only, no look-ahead, crisis excess recovered), crisis draws, and the mapping onto the fuel targets.

Synthetic data only.
"""

import numpy as np
import pandas as pd
import pytest

import margins as mg

IDX = pd.date_range("1990-01-01", "2025-12-01", freq="MS")
TRUE = {"const": 0.0, "gap": -0.2, "momentum": -0.05, "sticky": 0.8, "brent": -0.1}


def synthetic(seed=0, excess=0.0, sd=0.03):
    """A margin that follows the margin equation exactly (no seasonality), plus `excess` added to
    its change in the first three months of every listed crisis."""
    rng = np.random.default_rng(seed)
    x = np.r_[np.nan, rng.normal(0, 0.08, len(IDX) - 1)]
    r = np.full(len(IDX), 0.2)
    onsets = [pd.Timestamp(o) for o, _ in mg.EVENTS]
    for t in range(2, len(IDX)):
        X = mg.regressors(r[t - 1], r[t - 1] - r[t - 2], x[t], IDX[t].month, r[max(t - mg.LOCAL, 0):t].mean())
        b = np.array([TRUE["const"], 0, 0, 0, 0, TRUE["gap"], TRUE["momentum"], TRUE["sticky"], TRUE["brent"]])
        d = X @ b + sd * rng.standard_normal()
        if any(0 <= mg.months_since(IDX[t], o) < 3 for o in onsets):
            d += excess
        r[t] = r[t - 1] + d
    return {"index": IDX, "x": x, "r": {"diesel": r}, "brent": 60 * np.exp(np.nancumsum(np.r_[0, x[1:]]))}


def test_crack_identity_and_splice():
    days = pd.bdate_range("2004-01-01", "2008-12-31")
    rng = np.random.default_rng(1)
    brent = pd.Series(60 * np.exp(np.cumsum(rng.normal(0, 0.01, len(days)))), index=days)
    ho = brent / 42 * 1.20  # $/gal: heating oil 20% over Brent
    ulsd = (brent / 42 * 1.25)[days >= "2006-06-14"]  # ULSD 25% over Brent, from mid-2006
    spot = {mg.SERIES["ulsd_nyh"][0]: ulsd, mg.SERIES["heating_oil_nyh"][0]: ho}
    for k in ("jet_usgc", "gasoline_usgc", "rbob_la"):
        spot[mg.SERIES[k][0]] = ho
    mm = mg.build(brent, spot, start="2004-01-01")
    r = mm["r"]["diesel"]
    # exactly Brent's monthly log change plus the margin's
    logp = np.log(mm["price"]["ulsd_nyh"])
    ok = np.isfinite(logp) & (mm["index"] >= "2006-07-01")  # ULSD's first, partial month is replaced by the splice
    assert np.allclose(np.diff(logp)[ok[1:] & ok[:-1]], (mm["x"][1:] + np.diff(r))[ok[1:] & ok[:-1]])
    # before ULSD starts, heating oil's log ratio plus the overlap's offset: continuous across the joint
    assert np.allclose(r[mm["index"] >= "2006-07-01"], np.log(1.25), atol=1e-12)
    assert np.allclose(r[mm["index"] < "2006-06-01"], np.log(1.25), atol=1e-9)


def test_sticky_term_is_the_change_of_a_fixed_dollar_crack():
    B0, crack, x = 70.0, 20.0, 0.3
    r0 = np.log((B0 + crack) / B0)
    B1 = B0 * np.exp(x)
    r1 = np.log((B1 + crack) / B1)
    X = mg.regressors(r0, 0.0, x, 3, r0 - 0.05)
    assert X[mg.FEATURES.index("sticky")] == pytest.approx(r1 - r0)
    assert X[mg.FEATURES.index("brent")] == x and X[0] == 1.0
    assert X[mg.FEATURES.index("gap")] == pytest.approx(0.05)
    assert np.all(mg.regressors(r0, 0.0, x, None, r0)[1:5] == 0)  # no month: no seasonal terms
    # a negative crack that a Brent crash would push below zero is held at -90% of Brent
    assert np.isfinite(mg.regressors(np.log(0.8), 0.0, -1.0, 3, 0.0)).all()


def test_fit_recovers_the_equation_and_the_crisis_excess():
    mm = synthetic(excess=0.08)
    f = mg.fit(mm, "diesel", pd.Timestamp("2025-12-01"))
    for k in ("gap", "momentum"):
        assert f.beta[mg.FEATURES.index(k)] == pytest.approx(TRUE[k], abs=0.05), k
    for x in (-0.15, 0.15):  # sticky and brent are nearly collinear; their joint response is what matters
        row = mg.regressors(0.2, 0.0, x, None, 0.2)
        true = TRUE["sticky"] * row[mg.FEATURES.index("sticky")] + TRUE["brent"] * x
        assert row @ f.beta == pytest.approx(true, abs=0.01)
    for onset in ("1990-08", "2005-09", "2011-03", "2022-03"):
        e = f.excess[onset]
        assert np.mean(e[:3]) == pytest.approx(0.08, abs=0.04)  # recovered, not absorbed by the fit
        assert abs(np.mean(e[3:])) < 0.04
    assert "2026-03" not in f.excess  # after the training end
    assert f.z.std() == pytest.approx(1.0, abs=0.05)


def test_fit_does_not_look_past_the_training_end():
    mm = synthetic(seed=3)
    last = pd.Timestamp("2010-06-01")
    a = mg.fit(mm, "diesel", last)
    later = mm["index"] > last
    mm["r"]["diesel"] = np.where(later, mm["r"]["diesel"] + np.random.default_rng(9).normal(0, 1, len(IDX)), mm["r"]["diesel"])
    mm["x"] = np.where(later, -mm["x"], mm["x"])
    b = mg.fit(mm, "diesel", last)
    assert np.array_equal(a.beta, b.beta) and np.array_equal(a.ref, b.ref) and a.vol == b.vol
    assert sorted(a.excess) == ["1990-08", "2005-09"]
    for o in a.excess:
        assert np.array_equal(a.excess[o], b.excess[o], equal_nan=True)


def test_known_events_by_mode():
    origin = pd.Timestamp("2022-05-01")
    assert len(mg.known_events(origin, "whatif")) == len(mg.EVENTS)  # given what happened, like the Brent path
    ongoing = mg.known_events(origin, "forecast")
    assert ongoing == [(pd.Timestamp("2022-03-01"), 1.0)]  # only the crisis already under way
    assert mg.known_events(pd.Timestamp("2024-01-01"), "forecast") == []
    scen = mg.known_events(pd.Timestamp("2026-02-01"), "forecast", lost=41.0)
    assert scen == [(pd.Timestamp("2026-03-01"), 0.5)]
    # a 0-point scenario carries its crisis at scale 0, so it picks crises like every other scenario
    assert mg.known_events(pd.Timestamp("2026-02-01"), "forecast", lost=0.0) == [(pd.Timestamp("2026-03-01"), 0.0)]


def test_scenarios_pick_crises_from_the_same_random_numbers():
    f = mg.fit(synthetic(excess=0.08), "diesel", pd.Timestamp("2025-12-01"))
    origin, onset = pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-01")
    r0, r1 = np.random.default_rng(7), np.random.default_rng(7)
    zero = mg.crisis_paths(f, origin, [(onset, 0.0)], 50, r0)
    half = mg.crisis_paths(f, origin, [(onset, 0.5)], 50, r1)
    assert np.all(zero == 0) and np.any(half != 0)
    assert r0.random() == r1.random()  # both streams moved on by the same draws


def test_crisis_paths_land_on_the_right_months():
    f = mg.fit(synthetic(excess=0.08), "diesel", pd.Timestamp("2025-12-01"))
    rng = np.random.default_rng(0)
    E = f.events()
    out = mg.crisis_paths(f, pd.Timestamp("2026-01-01"), [(pd.Timestamp("2026-03-01"), 0.5)], 2000, rng)
    assert np.all(out[:, 0] == 0)  # 2026-02 is before the onset
    assert np.allclose(np.sort(np.unique(out[:, 1])), np.sort(np.unique(0.5 * E[:, 0])))  # month 0 of a past crisis
    assert out[:, 1].mean() == pytest.approx(0.5 * E[:, 0].mean(), abs=0.01)
    assert np.all(mg.crisis_paths(f, pd.Timestamp("2026-01-01"), [], 10, rng) == 0)


def test_simulation_without_noise_follows_the_equation():
    mm = synthetic(seed=2)
    f = mg.fit(mm, "diesel", pd.Timestamp("2025-12-01"))
    i = len(IDX) - 13
    xf = np.zeros((3, 12))
    dr = mg.simulate(f, mm, i, xf, np.zeros((3, 12)), np.random.default_rng(0), noise=False)
    r, b = mm["r"]["diesel"], f.beta
    r1 = r[i] + mg.regressors(r[i], r[i] - r[i - 1], 0.0, IDX[i + 1].month, mg.local_mean(r)[i]) @ b
    assert dr[:, 0] == pytest.approx(r1 - r[i])
    assert np.allclose(dr, dr[0])  # same path for every draw
    crisis = np.zeros((3, 12))
    crisis[:, 0] = 0.1
    bumped = mg.simulate(f, mm, i, xf, crisis, np.random.default_rng(0), noise=False)
    assert bumped[0, 0] == pytest.approx(dr[0, 0] + 0.1)
    # month 2: the margin is 0.1 higher and so is 1/60 of its five-year mean
    kappa, phi = b[mg.FEATURES.index("gap")], b[mg.FEATURES.index("momentum")]
    assert bumped[0, 1] - dr[0, 1] == pytest.approx(0.1 * (kappa * (1 - 1 / mg.LOCAL) + phi))


def test_news_is_only_what_the_margin_state_adds():
    mm = synthetic(seed=6)
    f = mg.fit(mm, "diesel", pd.Timestamp("2025-12-01"))
    f.beta[1:5] = 0.0  # no seasonality, so a neutral state has nothing to add
    i = len(IDX) - 13
    r = mm["r"]["diesel"]
    xf = np.random.default_rng(1).normal(0, 0.1, (2, 12))
    beta = np.broadcast_to(f.beta, (2, len(f.beta)))
    r[i - mg.LOCAL + 1:i + 1] = 0.25  # five years flat: no gap, no momentum
    assert np.allclose(mg.news(f, mm, i, xf, np.zeros((2, 12)), beta), 0, atol=1e-12)
    r[i] = 0.35  # the margin jumps 0.1 above its mean in the origin month
    nw = mg.news(f, mm, i, xf, np.zeros((2, 12)), beta)
    assert np.all(nw[:, 0] < 0)  # reversion pulls it back, whatever Brent does
    assert np.all(np.cumsum(nw, 1)[:, -1] > -0.1)  # and not past the mean


def test_correction_follows_the_lags_and_the_own_lag():
    mp = mg.Map("ind_gasdesw", ("diesel",), np.array([0.0, 1.0, 0.5, 0.0]), np.zeros(5), 1.0)
    news = {"diesel": np.zeros((2, 6))}
    assert np.all(mg.correction(mp, news) == 0)
    news["diesel"][:, 0] = 0.01  # the margin 1% higher in month 1, nothing after
    assert np.allclose(mg.correction(mp, news)[0], [1.0, 1.5, 1.5, 1.5, 1.5, 1.5])
    mp.coef[-1] = 0.5  # own lag: half of each month's change carries into the next
    d = mg.correction(mp, news)[0]
    inc = np.diff(np.r_[0, d])
    assert inc[0] == pytest.approx(1.0) and inc[1] == pytest.approx(0.5 * 1.0 + 0.5) and inc[2] == pytest.approx(0.5 * inc[1])


def test_member_with_an_identity_map_is_brent_plus_margin():
    mm = synthetic(seed=4)
    i = len(IDX) - 13
    target = pd.Series(mg.product_changes(mm, "diesel"), index=IDX)
    mp = mg.Map("ind_djfuelusgulf", ("diesel",), np.array([0.0, 1.0, 0.0, 0.0]), np.zeros(5), 1.0)
    rng = np.random.default_rng(0)
    xf, drs = rng.normal(0, 0.05, (4, 12)), {"diesel": rng.normal(0, 0.02, (4, 12))}
    out = mg.member(mp, mm, target, i, 1, xf, drs, rng)
    assert np.allclose(out, 100 * np.cumsum(xf + drs["diesel"], 1))


def test_crack_levels_hold_when_nothing_moves():
    mm = synthetic(seed=5)
    i = len(IDX) - 13
    c = mg.crack_levels(mm, i, "diesel", np.zeros((2, 12)), np.zeros((2, 12)))
    assert np.allclose(c, mm["brent"][i] * np.expm1(mm["r"]["diesel"][i]))
