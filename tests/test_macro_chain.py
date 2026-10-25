"""experiments/macro_chain.py: the mixture keeps every draw paired with its oil path, the weight grid,
and forward weights that only look at earlier folds.

Synthetic data only. Needs torch, jax and numpyro (skipped otherwise).
"""

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("numpyro")
import macro_chain as mc  # noqa: E402


def test_weight_grid_has_corners_and_equal_weights():
    for m, size in ((4, 35), (3, 16)):  # 3 members: 15 grid points plus 1/3 each
        W = mc.simplex(m)
        assert len(W) == size
        assert np.allclose(W.sum(1), 1)
        assert any(np.allclose(w, np.full(m, 1 / m)) for w in W)
        for i in range(m):
            assert any(np.allclose(w, np.eye(m)[i]) for w in W)


def test_assignment_counts_follow_the_weights():
    order = np.random.default_rng(0).permutation(400)
    a = mc.assignment(np.array([0.5, 0.25, 0.25, 0.0]), 400, order)
    assert np.bincount(a, minlength=4).tolist() == [200, 100, 100, 0]
    b = mc.assignment(np.full(3, 1 / 3), 400, order)
    assert sorted(np.bincount(b).tolist()) == [133, 133, 134]


def test_mixture_keeps_each_draw_with_its_oil_path():
    rng = np.random.default_rng(0)
    S = rng.normal(size=(3, 50, 4, 2))  # members, draws, origins, outputs
    order = rng.permutation(50)
    w = np.array([0.5, 0.25, 0.25])
    M = mc.mixture(S, w, order)
    a = mc.assignment(w, 50, order)
    for n in range(50):  # draw n is member a[n]'s draw n, not some other draw
        assert np.array_equal(M[n], S[a[n], n])
    assert np.array_equal(mc.mixture(S, np.array([0.0, 1.0, 0.0]), order), S[1])


def test_calibration_factor_hits_the_target_coverage():
    rng = np.random.default_rng(0)
    y = rng.normal(size=20_000)
    q = 1.645 * 0.8  # a forecast whose 90% band is 20% too narrow
    inside = np.array([np.abs(y) <= s * q for s in mc.SPREAD])
    assert mc.calibration_factor(inside) == pytest.approx(1.25, abs=0.05)


def test_empirical_crps_matches_the_sample_formula():
    rng = np.random.default_rng(1)
    train = rng.normal(size=(300, 2))
    train[:10, 1] = np.nan  # missing training outcomes are skipped
    y = np.array([[0.5, np.nan], [-1.0, 2.0]])
    out = mc.empirical_crps(train, y)
    s = train[:, 0]
    expect = np.mean(np.abs(s - 0.5)) - 0.5 * np.mean(np.abs(s[:, None] - s[None, :]))
    assert out[0, 0] == pytest.approx(expect, rel=1e-9)
    assert np.isnan(out[0, 1]) and np.isfinite(out[1, 1])


def test_forward_choice_uses_earlier_folds_only():
    score = np.array([[1.0, 0.5, 0.9],   # fold 0
                      [1.0, 0.6, 0.9],   # fold 1
                      [1.0, 0.9, 0.1]])  # fold 2 prefers combination 2, but fold 2 can't see itself
    assert mc.forward_choice(score, 0, equal=0) == 0
    assert mc.forward_choice(score, 2, equal=0) == 1


def test_regime_ensembles_pair_the_bayesian_draws():
    rng = np.random.default_rng(3)
    S = {m: rng.normal(size=(30, 2, 3)) for m in ("bayes_own", "bayes_regime", "global_lin", "global")}
    order = rng.permutation(30)
    out = mc.regime_models(lambda m: S[m], order)
    a = mc.assignment(np.full(3, 1 / 3), 30, order)
    for n in range(30):  # draw n comes from the Bayesian member in both ensembles, or from the same network
        if a[n] == 0:
            assert np.array_equal(out["rec"][n], S["bayes_own"][n]) and np.array_equal(out["rec_regime"][n], S["bayes_regime"][n])
        else:
            assert np.array_equal(out["rec"][n], out["rec_regime"][n])
    assert np.array_equal(out["bayes_regime"], S["bayes_regime"])


def test_regime_keep_rule():
    fine = {("whatif", "inflation"): -1.0, ("levy", "cost"): 1.9}
    better, worse = {"rec": (0.50, 0.80), "rec_regime": (0.40, 0.85)}, {"rec": (0.50, 0.80), "rec_regime": (0.55, 0.85)}
    assert mc.regime_verdict(fine, better) == (True, [])
    keep, why = mc.regime_verdict(fine | {("levy", "rate"): 2.4}, better)  # one group worse beyond 2 errors
    assert not keep and "rate" in why[0]
    assert not mc.regime_verdict(fine, worse)[0]  # the replay must improve
    assert not mc.regime_verdict(fine, {"rec": (0.50, 0.80), "rec_regime": (0.40, 0.70)})[0]  # without losing coverage


def test_margin_member_joins_mixtures_on_the_fuel_columns_only():
    rng = np.random.default_rng(2)
    S = rng.normal(size=(3, 400, 2, 5))  # members, draws, origins, outputs
    D = rng.normal(size=(400, 2, 5)) + 100  # the margin member, easy to recognise
    order = rng.permutation(400)
    cols, other = [1, 3], [0, 2, 4]
    w = np.full(3, 1 / 3)
    M = mc.with_margins(S, D, w, order, cols)
    base = mc.mixture(S, w, order)
    assert np.array_equal(M[..., other], base[..., other])  # other targets: the members alone
    a4 = mc.assignment(np.full(4, 0.25), 400, order)  # one more equal-weight member, same order
    for n in range(400):  # draw n keeps oil path n whichever member it comes from
        expect = D[n] if a4[n] == 3 else S[a4[n], n]
        assert np.array_equal(M[n][..., cols], expect[..., cols])
    assert (M[:, 0, cols[0]] > 50).sum() == 100
    one = np.array([0.0, 1.0, 0.0])  # a single member, or no margin draws, is left alone
    assert np.array_equal(mc.with_margins(S, D, one, order, cols), S[1])
    assert np.array_equal(mc.with_margins(S, None, w, order, cols), base)
    names = ["us_cpi@1", "ind_gasdesw@3", "ind_djfuelusgulf@12", "ind_pcu324110324110@1", "ind_pcu325311325311@1"]
    assert mc.fuel_columns(names) == [1, 2, 3]


def test_paired_rng_keeps_the_student_t_marginal():
    from scipy import stats
    x = mc.PairedRNG(np.random.default_rng(0)).standard_t(np.full(20000, 4.0))
    assert stats.kstest(x, "t", args=(4.0,)).pvalue > 0.01
    rng = mc.PairedRNG(np.random.default_rng(1))
    assert rng.standard_t(np.full((5, 1, 3), 6.0), size=(5, 2, 3)).shape == (5, 2, 3)  # as macro_bayes asks
    assert rng.standard_normal(4).shape == (4,)  # everything else passes through


def test_paired_rng_stays_in_step_whatever_the_df():
    a, b = mc.PairedRNG(np.random.default_rng(3)), mc.PairedRNG(np.random.default_rng(3))
    xa, xb = a.standard_t(np.full(500, 2.6)), b.standard_t(np.linspace(3, 40, 500))
    assert np.all(np.sign(xa) == np.sign(xb))  # one uniform each: the same quantile, a different df
    assert a.random() == b.random()


def test_network_noise_is_paired_across_oil_paths():
    from types import SimpleNamespace

    import macro_global as mg
    import torch
    from torch import nn

    class OilTails(nn.Module):
        """Location 0, unit scale and a tail index that moves with Brent's change at lag 0, as a
        trained head's can: numpy's own t sampler then uses a different number of draws per path."""

        def forward(self, x, k):
            return 0 * x[:, 0], torch.ones(len(x)), 2.6 + 30 * torch.abs(x[:, mg.OWN])

    M, K, n = 60, 2, 300
    st = SimpleNamespace(xs=1.0, x2=1.0, vm=0.0, vs=1.0, ym=np.zeros(K), ys=np.ones(K))
    info = {"keys": ["s0", "s1"], "pub_lag": np.array([0, 0])}
    data = {"oil_m": np.zeros(M), "dM": np.zeros((M, K))}
    calm, shock = np.zeros((n, 1, 12)), np.full((n, 1, 12), 0.3)
    run = lambda fut: mg.simulate([OilTails()], st, info, data, np.array([40]), fut,  # noqa: E731
                                  mc.PairedRNG(np.random.default_rng(9)), n=n)[:, 0]
    a, b = run(calm), run(shock)
    first = [k * len(mc.mn.HORIZONS) for k in range(K)]  # month 1 of each series
    assert np.all(np.sign(a[:, first]) == np.sign(b[:, first]))
    last = [k * len(mc.mn.HORIZONS) + len(mc.mn.HORIZONS) - 1 for k in range(K)]  # month 12
    assert min(np.corrcoef(a[:, c], b[:, c])[0, 1] for c in last) > 0.8


def test_effect_is_taken_draw_by_draw():
    rng = np.random.default_rng(4)
    base = rng.normal(size=1000)
    assert mc.effect(base, base) == (0.0, 0.0, 0.0, 0.0)
    assert mc.effect(base + 2.0, base) == pytest.approx((2.0, 2.0, 2.0, 2.0))  # no base noise in the band
