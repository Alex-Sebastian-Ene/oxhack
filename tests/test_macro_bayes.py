"""experiments/macro_bayes.py: sample CRPS, the month-by-month simulation, nowcasting from the last
published month, the oil-shock response and the bootstrap oil paths.

Synthetic data only: no downloads and no MCMC. Needs torch, jax and numpyro (skipped otherwise).
"""

from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("numpyro")
import macro_bayes as mb  # noqa: E402
import macro_nn as mn  # noqa: E402

M, K = 60, 2


def toy(rho=0.0, a=0.0, alpha=0.0, b0=0.0, n=3):
    """Posterior with n identical draws, two series, stats that make standardised = real units."""
    B = np.zeros((n, K, mb.LAGS))
    B[:, :, 0] = b0
    post = {"B": B, "a": np.full((n, K), a), "rho": np.full((n, K), rho), "alpha": np.full((n, K), alpha),
            "sigma": np.full((n, K), 1e-9), "phi": np.zeros((n, K)), "nu": np.full((n, K), 5.0)}
    st = SimpleNamespace(xs=1.0, x2=1.0, vm=0.0, vs=1.0, ym=np.zeros(K), ys=np.ones(K))
    info = {"keys": ["s0", "s1"], "pub_lag": np.array([0, 1])}
    data = {"oil_m": np.zeros(M), "dM": np.zeros((M, K))}
    return post, st, info, data


def test_sample_crps_matches_gaussian():
    rng = np.random.default_rng(0)
    S = rng.normal(1.0, 2.0, size=(200_000, 3))
    y = np.array([0.0, 1.0, 4.0])
    assert mb.crps_samples(S, y) == pytest.approx(mn.gaussian_crps(1.0, 4.0, y), rel=1e-2)


def test_drift_accumulates_over_horizons():
    post, st, info, data = toy(a=0.5)
    out = mb.simulate(post, st, info, data, np.array([40]), np.zeros((1, 1, 12)), np.random.default_rng(0), noise=False)
    h = np.array(mn.HORIZONS, float)
    assert out[0, 0, :4] == pytest.approx(0.5 * h)  # series 0, target-major then horizon
    assert out[0, 0, 4:] == pytest.approx(0.5 * h)


def test_nowcast_starts_from_last_published_month():
    post, st, info, data = toy(rho=0.5)
    t = 40
    data["dM"][t - 1] = 1.0  # last month published for the lag-1 series
    data["dM"][t] = 1.0      # published only for the lag-0 series
    out = mb.simulate(post, st, info, data, np.array([t]), np.zeros((1, 1, 12)), np.random.default_rng(0), noise=False)
    # lag 0: month t is known (1.0), so month t+1 = 0.5. Lag 1: month t is nowcast as 0.5, so t+1 = 0.25.
    assert out[0, 0, 0] == pytest.approx(0.5)
    assert out[0, 0, 4] == pytest.approx(0.25)


def test_oil_path_enters_with_asymmetry():
    post, st, info, data = toy(alpha=0.5, b0=1.0)
    fut = np.zeros((1, 1, 12))
    fut[0, 0, 0] = 0.1
    up = mb.simulate(post, st, info, data, np.array([40]), fut, np.random.default_rng(0), noise=False)
    down = mb.simulate(post, st, info, data, np.array([40]), -fut, np.random.default_rng(0), noise=False)
    assert up[0, 0, 0] == pytest.approx(0.15)  # rises pass through at 1 + alpha
    assert down[0, 0, 0] == pytest.approx(-0.05)  # falls at 1 - alpha


def test_shock_response_matches_simulation():
    post, st, info, _ = toy(rho=0.5, alpha=0.2, b0=2.0)
    e = mb.responses(post, st, info, np.log(1.10))
    first = 2.0 * np.log(1.10) * 1.2
    assert e[0, 0, 0] == pytest.approx(first)
    assert e[0, 0, 2] == pytest.approx(first * (1 + 0.5 + 0.25))  # momentum carries the move on


def test_scale_floor_holds_in_calm_months():
    post, st, info, data = toy(n=20_000)
    post["phi"][:] = 5.0  # calm oil (all zero) makes exp(phi * v) vanish
    post["nu"][:] = 1e6
    info["floor"] = np.array([1.0, 1.0])
    out = mb.simulate(post, st, info, data, np.array([40]), np.zeros((1, 1, 12)), np.random.default_rng(0))
    assert out[:, 0, 0].std() == pytest.approx(1.0, rel=0.05)  # the floor, not ~0


def test_drifting_volatility_grows_with_distance_from_training():
    post, st, info, data = toy(n=4000)
    post["nu"][:] = 1e6
    post["sigma"][:] = 1.0
    post["omega"], post["h_last"] = np.full((4000, 4), 0.5), np.zeros((4000, 4))
    info["vgroup"] = np.array([0, 0])
    st.last = 20
    near, far = mb.simulate(post, st, info, data, np.array([21, 45]), np.zeros((1, 2, 12)), np.random.default_rng(0)).transpose(1, 0, 2)
    # 24 more months of log-volatility drift: the median scale stays ~1, the tails fan out
    tail = lambda x: np.quantile(np.abs(x), 0.95)  # noqa: E731
    assert tail(far[:, 0]) > 2 * tail(near[:, 0])


def test_futures_drift_centres_the_oil_paths():
    rng = np.random.default_rng(0)
    data = {"oil_m": np.r_[np.nan, rng.normal(0, 0.05, 200)]}
    st = SimpleNamespace(x2=float(np.nanmean(data["oil_m"][1:] ** 2)))
    drift = np.zeros((201, 12))
    drift[:, 0] = 0.02
    market = {"ovx": np.full(201, np.nan), "drift": drift}
    p = mb.oil_paths(data, st, 200, np.array([150]), 20_000, rng, market)
    assert p[:, 0, 0].mean() == pytest.approx(0.02, abs=0.002)
    assert abs(p[:, 0, 5].mean()) < 0.002


def test_responses_carry_on_past_the_oil_lags():
    post, st, info, _ = toy(rho=0.5, b0=1.0)
    e = mb.responses(post, st, info, np.log(1.10), months=36)
    g = np.log(1.10)
    assert e.shape[-1] == 36
    assert e[0, 0, 35] == pytest.approx(g / (1 - 0.5), rel=1e-6)  # the geometric sum of the momentum


def test_bootstrap_oil_paths_scale_with_recent_volatility():
    rng = np.random.default_rng(0)
    data = {"oil_m": np.r_[np.nan, rng.normal(0, 0.05, 200), np.full(3, 0.5)]}
    st = SimpleNamespace(x2=float(np.nanmean(data["oil_m"][1:201] ** 2)))
    calm, wild = 150, 203
    p = mb.oil_paths(data, st, 200, np.array([calm, wild]), 4000, rng)
    assert p.shape == (4000, 2, 12)
    assert abs(p[:, 0].mean()) < 0.005  # demeaned
    assert p[:, 1, 0].std() > 2 * p[:, 0, 0].std()  # turmoil at the origin widens the first months
    assert p[:, 1, -1].std() < p[:, 1, 0].std()  # and decays back
