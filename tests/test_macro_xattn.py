"""experiments/macro_xattn.py: token inputs, the joint month-by-month simulation (nowcasting from each
token's last published month), and that attention picks up an effect carried by another series.

Synthetic data only: no downloads. Needs torch, jax and numpyro (skipped otherwise).
"""

from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("numpyro")
import torch  # noqa: E402
from torch import nn  # noqa: E402

import macro_xattn as mx  # noqa: E402

M, K, C = 60, 2, 1


class Stub(nn.Module):
    """Every token's location is coef x its own last change; a negligible scale."""

    def __init__(self, coef: float) -> None:
        super().__init__()
        self.coef = coef

    def forward(self, x):
        return self.coef * x[..., 0], torch.full(x.shape[:2], 1e-9), torch.full(x.shape[:2], 5.0)


def toy():
    st = SimpleNamespace(xs=1.0, vm=0.0, vs=1.0, ym=np.zeros(K), ys=np.ones(K))
    ts = SimpleNamespace(ym=np.zeros(K + C), ys=np.ones(K + C))
    info = {"keys": ["s0", "s1"], "pub_lag": np.array([0, 1])}
    ctx = {"keys": ["c0"], "dM": np.zeros((M, C)), "lag": np.array([0])}
    data = {"oil_m": np.zeros(M), "dM": np.zeros((M, K))}
    return st, ts, info, ctx, data


def test_inputs_layout():
    own = np.arange(2 * 3 * mx.OWN, dtype=float).reshape(2, 3, mx.OWN)  # [B, T, OWN]
    own[1, 2, :] = np.nan
    oil, v = np.ones((2, 13)), np.full(2, 7.0)
    x = mx.inputs(own, oil, v)
    assert x.shape == (2, 3, mx.OWN + 13 + 2)
    assert np.array_equal(x[0, 1, :mx.OWN], own[0, 1]) and np.all(x[..., mx.OWN:mx.OWN + 13] == 1)
    assert np.all(x[..., -2] == 7.0)
    assert x[1, 2, -1] == 0 and x[0, 0, -1] == 1  # availability flag
    assert np.all(x[1, 2, :mx.OWN] == 0)


def test_nowcast_starts_from_each_tokens_last_published_month():
    st, ts, info, ctx, data = toy()
    t = 40
    data["dM"][t - 1] = 1.0  # last month published for the lag-1 target
    data["dM"][t] = 1.0      # published only for the lag-0 target
    ctx["dM"][t] = 2.0       # the context token (lag 0) is known at t
    state = {"ctx": ctx, "ts": ts}
    out = mx.simulate([Stub(0.5)], state, st, info, data, np.array([t]), np.zeros((1, 1, 12)), None, n=1, noise=False)
    assert out.shape == (1, 1, K * 4)
    assert out[0, 0, 0] == pytest.approx(0.5)   # target 0: month t known (1), t+1 = 0.5
    assert out[0, 0, 4] == pytest.approx(0.25)  # target 1: month t nowcast as 0.5, t+1 = 0.25


def test_attention_learns_an_effect_carried_by_another_series():
    rng = np.random.default_rng(0)
    n = 320
    c = rng.normal(size=n)  # a context series ...
    y = np.r_[0.0, 0.9 * c[:-1]] + 0.3 * rng.normal(size=n)  # ... whose last change drives the target's
    Y = np.column_stack([y, c])
    oil, v = np.zeros((n, 13)), np.zeros(n)
    months, x, yy, mask = mx.training_rows(Y, oil, v, n - 1)
    net, info = mx.train(x, yy, mask, months, np.array([0.05, 0.05]), seed=0)
    with torch.no_grad():
        loc = net(torch.as_tensor(x, dtype=torch.float32))[0].numpy()[:, 0]
    truth = 0.9 * x[:, 1, 0]  # the context token's own last change
    assert info["best_epoch"] > 3
    assert np.corrcoef(loc, truth)[0, 1] > 0.9  # the target's own inputs alone carry none of it
