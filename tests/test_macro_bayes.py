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
