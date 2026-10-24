"""experiments/macro_global.py: input alignment, the month-by-month simulation (nowcasting from the
last published month, oil lags), and that training recovers a known relation.

Synthetic data only: no downloads. Needs torch, jax and numpyro (skipped otherwise).
"""

from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("numpyro")
import torch  # noqa: E402
from torch import nn  # noqa: E402

import macro_bayes as mb  # noqa: E402
import macro_global as mg  # noqa: E402

M, K = 60, 2


class Stub(nn.Module):
    """Location = coef . inputs, a negligible scale: a known one-step rule for the simulator."""

    def __init__(self, coef: dict) -> None:
        super().__init__()
        self.w = torch.zeros(mg.OWN + mb.LAGS + 1)
        for i, c in coef.items():
            self.w[i] = c

    def forward(self, x, k):
        return x @ self.w, torch.full((len(x),), 1e-9), torch.full((len(x),), 5.0)


def toy():
    st = SimpleNamespace(xs=1.0, x2=1.0, vm=0.0, vs=1.0, ym=np.zeros(K), ys=np.ones(K))
    info = {"keys": ["s0", "s1"], "pub_lag": np.array([0, 1])}
    data = {"oil_m": np.zeros(M), "dM": np.zeros((M, K))}
    return st, info, data


def run(net, st, info, data, t, fut):
    return mg.simulate([net], st, info, data, np.array([t]), fut, None, n=1, noise=False)[0, 0]


def test_inputs_line_up_with_months():
    rng = np.random.default_rng(0)
    st = SimpleNamespace(xs=1.0, vm=0.0, vs=1.0, ym=np.zeros(K), ys=np.ones(K))
    data = {"oil_m": rng.normal(size=M), "dM": rng.normal(size=(M, K))}
    f = mg.features(data, st)
    s, k, x, y = mg.training_rows(f, M - 1)
    i = np.flatnonzero((s == 30) & (k == 1))[0]
    assert y[i] == data["dM"][30, 1]
    assert x[i, 0] == data["dM"][29, 1] and x[i, mg.OWN - 1] == data["dM"][30 - mg.OWN, 1]  # own lags 1..OWN
    assert x[i, mg.OWN] == data["oil_m"][30] and x[i, mg.OWN + 12] == data["oil_m"][18]  # oil lags 0..12


def test_nowcast_starts_from_last_published_month():
    st, info, data = toy()
    t = 40
    data["dM"][t - 1] = 1.0  # last month published for the lag-1 series
    data["dM"][t] = 1.0      # published only for the lag-0 series
    out = run(Stub({0: 0.5}), st, info, data, t, np.zeros((1, 1, 12)))
    # lag 0: month t is known (1.0), so month t+1 = 0.5. Lag 1: month t is nowcast as 0.5, so t+1 = 0.25.
    assert out[0] == pytest.approx(0.5)
    assert out[4] == pytest.approx(0.25)


def test_oil_path_enters_at_the_right_lag():
    st, info, data = toy()
    fut = np.zeros((1, 1, 12))
    fut[0, 0, 0] = 0.1  # Brent moves in the first month after the origin
    now = run(Stub({mg.OWN: 1.0}), st, info, data, 40, fut)          # responds to oil in the same month
    later = run(Stub({mg.OWN + 1: 1.0}), st, info, data, 40, fut)    # responds a month later
    assert now[:2] == pytest.approx([0.1, 0.1])  # series 0 after 1 and 3 months
    assert later[:2] == pytest.approx([0.0, 0.1])


def test_training_recovers_momentum_and_oil():
    rng = np.random.default_rng(1)
    n = 400
    z = rng.normal(size=n)
    dM = np.zeros((n, K))
    for s in range(1, n):
        dM[s] = 0.5 * dM[s - 1] + np.array([0.8, -0.4]) * z[s] + 0.3 * rng.standard_normal(K)
    st = SimpleNamespace(xs=1.0, vm=0.0, vs=1.0, ym=np.zeros(K), ys=np.ones(K))
    f = mg.features({"oil_m": z, "dM": dM}, st)
    s, k, x, y = mg.training_rows(f, n - 1)
    net, info = mg.train(x, k, y, s, np.full(K, 0.05), linear=False, seed=0)
    assert info["best_epoch"] > 5  # it trained, unlike the windowed networks
    truth = 0.5 * x[:, 0] + np.where(k == 0, 0.8, -0.4) * x[:, mg.OWN]
    with torch.no_grad():
        loc = net(torch.as_tensor(x, dtype=torch.float32), torch.as_tensor(k))[0].numpy()
    assert np.corrcoef(loc, truth)[0, 1] > 0.95
