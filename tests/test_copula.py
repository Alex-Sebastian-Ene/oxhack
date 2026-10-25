"""experiments/copula.py: the t-copula draws keep each series' marginal and add the right dependence;
the correlation estimate; the joint scores.

Synthetic data only. Needs torch, jax and numpyro (skipped otherwise).
"""

import numpy as np
import pytest
from scipy import stats

pytest.importorskip("torch")
pytest.importorskip("numpyro")
import copula as cp  # noqa: E402
import macro_bayes as mb  # noqa: E402

R3 = np.array([[1.0, 0.7, 0.0], [0.7, 1.0, 0.3], [0.0, 0.3, 1.0]])


def cop(R=R3, nu=6.0):
    return {"R": R, "L": np.linalg.cholesky(R), "nu": nu}


def test_marginals_are_kept_and_dependence_added():
    rng = cp.CopulaRNG(np.random.default_rng(0), cop())
    df = np.array([3.0, 10.0, 1e6])
    x = rng.standard_t(df, size=(60_000, 3))
    for k in range(3):  # each column is still Student-t with its own df
        assert stats.kstest(x[:, k], "t", args=(df[k],)).pvalue > 0.01
    z = stats.norm.ppf(stats.rankdata(x, axis=0) / (len(x) + 1))
    assert np.corrcoef(z.T)[0, 1] == pytest.approx(0.7, abs=0.05)  # rank dependence follows R
    assert abs(np.corrcoef(z.T)[0, 2]) < 0.03


def test_other_shapes_pass_through():
    a = cp.CopulaRNG(np.random.default_rng(1), cop()).standard_t(np.full((5, 4), 5.0))  # 4 != K
    b = np.random.default_rng(1).standard_t(np.full((5, 4), 5.0))
    assert np.array_equal(a, b)


def test_broadcast_df_as_in_macro_bayes():
    rng = cp.CopulaRNG(np.random.default_rng(2), cop())
    out = rng.standard_t(np.full((7, 1, 3), 5.0), size=(7, 4, 3))  # macro_bayes.simulate's call
    assert out.shape == (7, 4, 3)


def test_correlation_is_a_valid_shrunk_estimate():
    rng = np.random.default_rng(3)
    z = rng.multivariate_normal(np.zeros(3), R3, size=4000)
    z[:500, 2] = np.nan  # a series that starts late
    R = cp.correlation(cp.normal_scores(z))
    assert np.allclose(np.diag(R), 1) and np.all(np.linalg.eigvalsh(R) > 0)
    assert R[0, 1] == pytest.approx((1 - cp.SHRINK) * 0.7, abs=0.04)


def test_tail_index_is_found():
    rng = cp.CopulaRNG(np.random.default_rng(4), cop(nu=3.0))
    x = rng.standard_t(np.full(3, 1e6), size=(5000, 3))  # normal marginals, t(3) copula
    u = stats.rankdata(x, axis=0) / (len(x) + 1)
    ll = [cp.t_copula_loglik(u, R3, nu) for nu in (3.0, 30.0)]
    assert ll[0] > ll[1]


def test_energy_score_in_one_dimension_is_the_crps():
    rng = np.random.default_rng(5)
    S = rng.normal(size=(4000, 1))
    assert cp.energy_score(S, np.array([0.7])) == pytest.approx(float(mb.crps_samples(S[:, 0], np.array(0.7))), rel=0.02)


def test_variogram_score_rewards_the_right_dependence():
    rng = np.random.default_rng(6)
    C = np.array([[1, 0.9], [0.9, 1]])
    right, wrong = [], []
    for _ in range(300):
        y = rng.multivariate_normal([0, 0], C)
        right.append(cp.variogram_score(rng.multivariate_normal([0, 0], C, size=500), y))
        wrong.append(cp.variogram_score(rng.normal(size=(500, 2)), y))
    assert np.mean(right) < np.mean(wrong)


def test_joint_scores_skip_missing_series():
    rng = np.random.default_rng(7)
    S = rng.normal(size=(200, 2, 6))  # 2 origins, 3 series x 2 horizons (series-major)
    y = rng.normal(size=(2, 6))
    y[0, [0, 2]] = np.nan  # origin 0: only one series left at horizon 1 -> no score
    H = np.array([1, 3, 1, 3, 1, 3])
    es, vs = cp.joint_scores(S, y, np.ones(6), H, (1, 3))
    assert np.isnan(es[0, 0]) and np.isfinite(es[0, 1]) and np.isfinite(es[1]).all()
