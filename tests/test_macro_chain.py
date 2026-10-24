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


def test_forward_choice_uses_earlier_folds_only():
    score = np.array([[1.0, 0.5, 0.9],   # fold 0
                      [1.0, 0.6, 0.9],   # fold 1
                      [1.0, 0.9, 0.1]])  # fold 2 prefers combination 2, but fold 2 can't see itself
    assert mc.forward_choice(score, 0, equal=0) == 0
    assert mc.forward_choice(score, 2, equal=0) == 1
