"""experiments/levy_fourier.py: the learned Lévy measure, the GARCH filter, scoring and fitting."""

import numpy as np
import pytest
from scipy import integrate, special, stats

import levy_fourier as lf
import non_gaussian as ng

Z = np.zeros(lf.K)
SHAPES = [
    (0.8, 1.1, 1.3, Z, Z),
    (0.6, 1.4, 1.2, np.array([0.5, -0.3, 0.2, 0, 0, 0.1]), np.array([-0.4, 0.6, 0, 0.2, -0.1, 0])),
    (1.5, 0.7, 0.8, np.array([0.3, 0, 0, 0, 0, 0]), Z),  # Y < 1: finite variation
]


@pytest.mark.parametrize("G,M,Y,a_up,a_down", SHAPES)
def test_innovation_is_a_zero_mean_unit_variance_density(G, M, Y, a_up, a_down):
    inn = lf.Levy(G, M, Y, a_up, a_down)
    f, dx = np.exp(inn.logf), lf.XG[1] - lf.XG[0]
    assert abs(f.sum() * dx - 1) < 1e-6
    assert abs((lf.XG * f).sum() * dx) < 1e-6
    assert abs((lf.XG ** 2 * f).sum() * dx - 1) < 1e-4
    assert np.all(np.diff(inn.cdf_grid) > 0) and inn.cdf_grid[0] < 1e-9 and inn.cdf_grid[-1] > 1 - 1e-9


def test_exponent_matches_direct_levy_khintchine_integral():
    G, M, Y, a_up, a_down = SHAPES[1]
    psi, var = lf.levy_psi(G, M, Y, a_up, a_down)

    def nu(x):
        s = abs(x)
        g = (a_up if x > 0 else a_down) @ lf.fourier_basis([s])[0] if s <= lf.L else 0.0
        return s ** (-1 - Y) * np.exp(-(M if x > 0 else G) * s + g)

    pieces = ((-80, -1), (-1, 0), (0, 1), (1, 80))
    for k in (1, 25, 120):
        u = lf.U[k]
        re = sum(integrate.quad(lambda x: (np.cos(u * x) - 1) * nu(x), a, b, limit=400)[0] for a, b in pieces)
        im = sum(integrate.quad(lambda x: (np.sin(u * x) - u * x) * nu(x), a, b, limit=400)[0] for a, b in pieces)
        assert abs(psi[k] - (re + 1j * im)) < 1e-7 * max(1, abs(re + 1j * im))
    assert var == pytest.approx(sum(integrate.quad(lambda x: x * x * nu(x), a, b, limit=400)[0]
                                    for a, b in ((-80, 0), (0, 80))), rel=1e-8)


def test_fourier_basis_vanishes_smoothly_at_both_ends_and_is_not_mirrored():
    s = np.array([1e-4, lf.L - 1e-4, 3.0, lf.L - 3.0])
    B = lf.fourier_basis(s)
    assert np.all(np.abs(B[:2]) < 1e-6)  # ~ s^2 at 0 and ~ (L - s)^2 at L
    even = B[:, 1::2]  # k = 2, 4, 6 are antisymmetric about L / 2
    assert np.allclose(even[2], -even[3]) and np.abs(even[2]).max() > 0.1
    g = lf.fourier_basis(np.array([3.0, 12.0])) @ np.array([0, 1.0, 0, 0, 0, 0])
    assert g[0] != pytest.approx(g[1])  # shape at 3 sd and at 12 sd can differ


def test_cgmy_part_is_the_same_process_as_in_non_gaussian():
    """Link: with no Fourier terms the learned measure is non_gaussian's CGMY, centred."""
    G, M, Y = 0.8, 1.1, 1.3
    psi1, var1 = lf.levy_psi(G, M, Y, Z, Z)
    C = 1 / var1
    mean = C * special.gamma(-Y) * Y * (G ** (Y - 1) - M ** (Y - 1))
    expected = ng.cgmy_psi({"mu": -mean, "C": C, "G": G, "M": M, "Y": Y}, lf.U)
    np.testing.assert_allclose(C * psi1, expected, rtol=1e-12, atol=1e-12)


def test_dct_density_equals_the_cosine_sum():
    rng = np.random.default_rng(3)
    psi = -0.5 * lf.U ** 2 + 0.1j * lf.U  # a Gaussian, so the series converges fast
    f = lf.cos_density(psi)
    coef = np.real(np.exp(psi + 1j * lf.U * lf.HALF)) / lf.HALF
    coef[0] /= 2
    idx = rng.integers(0, lf.TERMS, 20)
    direct = np.cos(np.outer(lf.XG[idx] + lf.HALF, lf.U)) @ coef
    np.testing.assert_allclose(f[idx], direct, atol=1e-12)
    np.testing.assert_allclose(f, stats.norm.pdf(lf.XG, 0.1, 1), atol=1e-12)


def returns(n=2500, seed=0):
    return np.random.default_rng(seed).standard_t(5, n) * 0.015


def test_density_falls_off_the_grid_so_a_collapsing_fit_loses():
    inn = lf.Levy(0.8, 1.1, 1.3, Z, Z)
    far = inn.logpdf(np.array([lf.HALF - 1, lf.HALF + 5, -lf.HALF - 5]))
    assert far[1] < far[0] - 200 and far[2] < far[0] - 200
    r, spec = returns(), lf.Spec("c", "levy")
    collapsed = lf.start(spec, r)
    collapsed[0], collapsed[1] = 7.0, -300.0
    assert lf.objective(collapsed, spec, r) > lf.objective(lf.start(spec, r), spec, r)


def test_fourier_model_with_zero_coefficients_is_cgmy_and_prior_is_ridge():
    r = returns()
    cgmy, fourier = lf.Spec("c", "levy"), lf.Spec("f", "levy", 1.0)
    t = lf.start(cgmy, r)
    assert lf.objective(np.concatenate([t, np.zeros(2 * lf.K)]), fourier, r) == pytest.approx(lf.objective(t, cgmy, r))
    a = np.linspace(-0.3, 0.3, 2 * lf.K)
    ta = np.concatenate([t, a])
    prior = lf.objective(ta, fourier, r) - lf.objective(ta, lf.Spec("f", "levy", 1e9), r)
    assert prior == pytest.approx(0.5 * np.sum((np.tile(lf.KS, 2) * a) ** 2), rel=1e-6)


@pytest.mark.parametrize("garch", [True, False])
def test_parameter_layout_puts_fourier_coefficients_where_describe_reads_them(garch):
    spec = lf.Spec("f", "levy", 1.0, garch)
    head = [0.0, np.log(1e-4)] + ([1.0, -1.0] if garch else []) + [0.1, 0.2, 0.3]
    a = np.arange(1, 2 * lf.K + 1) / 10
    t = np.array(head + list(a))
    assert spec.a0 == len(head)
    d = lf.describe(spec, t)
    assert d["a_up1"] == pytest.approx(0.1) and d[f"a_down{lf.K}"] == pytest.approx(2 * lf.K / 10)
    assert d["G"] == pytest.approx(np.exp(0.1)) and ("beta" in d) == garch


def test_garch_filter_matches_a_loop_and_iid_is_constant():
    r = returns(300)
    s = lf.garch_sigma(r, 0.001, 2e-5, 0.08, 0.9)
    loop = [np.sqrt(2e-5 / 0.02)]
    for i in range(1, len(r)):
        loop.append(np.sqrt(2e-5 + 0.08 * (r[i - 1] - 0.001) ** 2 + 0.9 * loop[-1] ** 2))
    np.testing.assert_allclose(s, loop, rtol=1e-12)
    mu, omega, alpha, beta, _ = lf.unpack(lf.Spec("g", "gauss", garch=False), np.array([0.0, np.log(4e-4)]))
    np.testing.assert_allclose(lf.garch_sigma(r, mu, omega, alpha, beta), 0.02, rtol=1e-12)


def gaussian_crps(mu, sd, y):
    z = (y - mu) / sd
    return sd * (z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - 1 / np.sqrt(np.pi))


def test_crps_and_pit_from_samples():
    rng = np.random.default_rng(5)
    x, y = rng.normal(size=(4, 400)), np.array([0.1, -1.0, 2.0, 0.0])
    brute = [np.mean(np.abs(s - v)) - 0.5 * np.mean(np.abs(s[:, None] - s[None, :])) for s, v in zip(x, y)]
    crps, pit = lf.crps_pit(x, y)
    np.testing.assert_allclose(crps, brute, atol=1e-12)
    np.testing.assert_allclose(pit, (x <= y[:, None]).mean(axis=1))


def test_simulated_horizons_match_the_gaussian_closed_form():
    """Link: the path simulator reproduces the analytic h-day law of an i.i.d. Gaussian model."""
    r = np.random.default_rng(1).normal(0.0005, 0.02, 600)
    spec, t = lf.Spec("g", "gauss", garch=False), np.array([0.0005, np.log(0.02 ** 2)])
    origins = np.arange(100, 400)
    out = lf.horizon_scores({"g": (spec, t)}, r, origins, paths=20000, seed=0)
    cum = np.concatenate([[0.0], np.cumsum(r)])
    for h in lf.HORIZONS:
        o = np.array(out["origins"])
        y = cum[o + h] - cum[o]
        exact = gaussian_crps(0.0005 * h, 0.02 * np.sqrt(h), y)
        assert np.mean(np.abs(np.array(out["models"]["g"][h]["crps"]) - exact)) < 0.01 * exact.mean()
        pit = stats.norm.cdf(y, 0.0005 * h, 0.02 * np.sqrt(h))
        assert np.max(np.abs(np.array(out["models"]["g"][h]["pit"]) - pit)) < 0.02


def test_hac_standard_error_grows_with_autocorrelation():
    rng = np.random.default_rng(2)
    e = rng.normal(size=20000)
    assert lf.hac_se(e, 10) == pytest.approx(e.std() / np.sqrt(len(e)), rel=0.1)
    ar = np.zeros_like(e)
    for i in range(1, len(e)):
        ar[i] = 0.8 * ar[i - 1] + e[i]
    assert lf.hac_se(ar, 30) > 2 * ar.std() / np.sqrt(len(ar))


def test_fit_recovers_garch_parameters_from_simulated_data():
    rng = np.random.default_rng(4)
    n, omega, alpha, beta = 4000, 1e-5, 0.08, 0.9
    r, s2 = np.empty(n), omega / (1 - alpha - beta)
    for i in range(n):
        r[i] = np.sqrt(s2) * rng.normal()
        s2 = omega + alpha * r[i] ** 2 + beta * s2
    spec = lf.Spec("g", "gauss")
    _, _, a_hat, b_hat, _ = lf.unpack(spec, lf.fit(spec, r))
    assert abs(a_hat - alpha) < 0.03 and abs(b_hat - beta) < 0.04


def test_fit_recovers_student_t_tail_index():
    r = np.random.default_rng(6).standard_t(4, 6000) * 0.01
    spec = lf.Spec("t", "student", garch=False)
    _, _, _, _, inn = lf.unpack(spec, lf.fit(spec, r))
    assert 3.0 < inn.nu < 5.5
