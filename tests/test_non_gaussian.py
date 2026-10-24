"""experiments/non_gaussian.py: Fourier-cosine densities, closed forms, Lévy time scaling, EWMA."""

import numpy as np
import pytest
from scipy import stats

import non_gaussian as ng

X = np.linspace(-0.25, 0.25, 801)
NIG = {"alpha": 32.0, "beta": -0.8, "delta": 0.02, "mu": 0.0008}
T = {"mu": 0.0005, "scale": 0.017, "nu": 3.4}


def cos_logpdf(model, p, x, h, half=3.0, terms=4096):
    data = ng.Data(x, ng.Cos(half, terms))
    f = data.basis @ data.cos.coef(h * model.psi(p, data.cos.u))
    return np.log(np.maximum(f, 1e-300))


def scipy_nig(p, h):
    d = p["delta"] * h
    return stats.norminvgauss(p["alpha"] * d, p["beta"] * d, p["mu"] * h, d)


def test_cos_density_matches_scipy_for_nig_and_student_t():
    np.testing.assert_allclose(cos_logpdf(ng.MODELS[2], NIG, X, 1.0), scipy_nig(NIG, 1).logpdf(X), atol=1e-8)
    np.testing.assert_allclose(cos_logpdf(ng.MODELS[1], T, X, 1.0),
                               stats.t.logpdf(X, T["nu"], T["mu"], T["scale"]), atol=1e-4)


@pytest.mark.parametrize("h", [5, 21])
def test_nig_time_scaling_is_closed_under_convolution(h):
    """Link: exp(h psi) of the daily fit is exactly the h-day NIG (delta h, mu h)."""
    x = np.linspace(-0.6, 0.6, 801)
    np.testing.assert_allclose(cos_logpdf(ng.MODELS[2], NIG, x, float(h), half=5.0),
                               scipy_nig(NIG, h).logpdf(x), atol=1e-7)


def test_student_t_time_scaling_matches_simulated_sums():
    """Link: the 5-day law from exp(5 psi) is the law of a sum of 5 daily t draws."""
    rng = np.random.default_rng(0)
    sums = (T["mu"] + T["scale"] * rng.standard_t(T["nu"], (200_000, 5))).sum(axis=1)
    grid = np.linspace(-1.0, 1.0, 4001)
    data = ng.Data(grid[:1], ng.Cos(4.0, 4096))
    cdf = data.cos.cdf(grid, data.cos.coef(5.0 * ng.student_psi(T, data.cos.u)))
    assert stats.kstest(sums, lambda y: np.interp(y, grid, cdf)).statistic < 0.005


def test_variance_gamma_closed_form_integrates_and_matches_cos_when_smooth():
    p = {"mu": 0.0006, "sigma": 0.025, "nu": 0.3, "theta": -0.002}
    grid = np.linspace(-1, 1, 400_001)
    f = np.exp(ng.vg_logpdf(p, grid, 1.0))
    assert np.trapezoid(np.nan_to_num(f), grid) == pytest.approx(1, abs=1e-4)
    # The series rings where the density is tiny (why VG is scored with the closed form), so
    # compare only where the density is above 1e-2.
    body = ng.vg_logpdf(p, X, 1.0) > np.log(1e-2)
    np.testing.assert_allclose(cos_logpdf(ng.MODELS[3], p, X, 1.0)[body], ng.vg_logpdf(p, X, 1.0)[body], atol=1e-4)
    assert ng.MODELS[3].unpack(np.array([0.0, 0.0, 50.0, 0.0]))["nu"] <= 2  # nu capped: no pole at h = 1


def test_merton_closed_form_matches_cos_and_jump_models_have_a_sigma_floor():
    p = {"mu": 0.0005, "sigma": 0.017, "lam": 0.2, "mu_j": -0.001, "sigma_j": 0.04}
    np.testing.assert_allclose(cos_logpdf(ng.MODELS[4], p, X, 1.0), ng.merton_logpdf(p, X, 1.0), atol=1e-6)
    assert ng.merton_cdf(p, np.array([-5.0, 5.0]), 1.0) == pytest.approx([0, 1], abs=1e-12)
    assert [m.name for m in ng.MODELS if m.sigma_floor] == ["Merton jump-diffusion", "Kou double-exponential jumps"]


def test_every_cos_cdf_is_monotone_from_zero_to_one():
    data = ng.Data(np.linspace(-0.5, 0.5, 201), ng.Cos(3.0, 4096))
    for model in ng.MODELS:
        p = model.unpack(np.array(model.start(0.0005, 0.025), float))
        c = ng.cdf(model, p, data, 1.0)
        assert np.all(np.diff(c) >= -1e-6), model.name  # VG's series wobbles at the 1e-7 level
        assert c[0] < 1e-3 and c[-1] > 1 - 1e-3, model.name


def test_ewma_volatility_uses_only_past_returns():
    r = np.random.default_rng(1).normal(0, 0.02, 300)
    s = ng.ewma_sigma(r)
    bumped = r.copy()
    bumped[200] += 0.5
    s2 = ng.ewma_sigma(bumped)
    np.testing.assert_array_equal(s[:201], s2[:201])
    assert s2[201] > s[201]


def test_coverage_and_hac():
    pit = np.linspace(0.0005, 0.9995, 1000)
    assert ng.coverage(pit) == pytest.approx([0.01, 0.05, 0.05, 0.01], abs=1e-3)
    d = np.random.default_rng(2).normal(0.1, 1, 5000)
    assert ng.diff_cell(d, np.zeros_like(d), 10).startswith("+0.")
