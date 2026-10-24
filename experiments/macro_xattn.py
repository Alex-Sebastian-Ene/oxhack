# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scipy>=1.11", "xlrd>=2.0", "openpyxl>=3.1", "torch>=2.2",
#                 "jax>=0.4.30", "numpyro>=0.15"]
# ///
"""Cross-series transformer for the knock-on chain: one token per series, attention across them.

Each month, every target series of macro_bayes.py (22) and every context series is a token. The
context series are asset prices and financial conditions:
    VIX (FRED VIXCLS), the BAA-Treasury spread (BAA10Y), NASDAQ (NASDAQCOM), 5-year breakevens
    (T5YIE, from 2003), the US and UK 10-year yields, GBP/USD and EUR/USD.

A token carries its own last 12 monthly changes, Brent's change at lags 0..12, the oil volatility
state of macro_bayes.py, an availability flag and a learned embedding. A small Transformer encoder
attends across the tokens of a month (not across time), so a move in yields, spreads or breakevens
can inform CPI and policy rates. Each token gets a Student-t for its next monthly change: the head
of macro_global.Net, plus a per-token linear term on its own inputs (as global_lin).

The context series are predicted too, so the system is simulated forward as a whole. In a what-if
only Brent's path is given, and the context series move with the simulation. Training and
simulation follow macro_global.py: one step ahead on the training months, early stopping on their
last quarter, a refit on all of them, and SEEDS networks per fit, with draw i from network i % SEEDS.

    uv run experiments/macro_xattn.py check   # tiny fit on the last fold: shapes, training, simulation
"""

from __future__ import annotations

import argparse
import copy
import time
from datetime import UTC, datetime

import numpy as np
import torch
from torch import nn

import macro_bayes as mb
import macro_data as md
import macro_global as mg
import macro_nn as mn

# (key, FRED code, transform): 100 x log change ("dlog") or change in points ("diff")
CONTEXT = (("vix", "VIXCLS", "dlog"), ("baa10y", "BAA10Y", "diff"), ("nasdaq", "NASDAQCOM", "dlog"),
           ("t5yie", "T5YIE", "diff"), ("us_10y", "DGS10", "diff"), ("uk_10y", "IRLTLT01GBM156N", "diff"),
           ("gbpusd", "DEXUSUK", "dlog"), ("eurusd", "DEXUSEU", "dlog"))
OWN = mg.OWN
D_MODEL, LAYERS, HEADS = 32, 2, 4
TRAIN = mg.TRAIN | {"batch": 32}  # a batch is 32 months, each with every token
SEEDS = mg.SEEDS
SEED_OFFSET = 500  # network s of a fit gets seed base_seed + SEED_OFFSET + s
QUICK = False


# --- data ------------------------------------------------------------------------------------

def context(data: dict) -> dict:
    """Monthly changes of the context series on the monthly arrays' index [M, C], with their
    publication lags (market data: 0; registry lag where the panel has the series) and fetch date."""
    idx = mb.month_index(data)
    reg = {s.key: s for s in md.registry(md.BLOCKS)}
    cols, lags, fetched = [], [], []
    for key, code, tr in CONTEXT:
        lv = md.fetch_fred(code).reindex(idx).values.astype(float)
        lv = np.log(lv) * 100 if tr == "dlog" else lv
        cols.append(np.r_[np.nan, np.diff(lv)])
        lags.append(reg[key].lag if key in reg else 0)
        fetched.append(datetime.fromtimestamp((md.RAW / f"fred_{code}.csv").stat().st_mtime, UTC).date().isoformat())
    return {"keys": [c[0] for c in CONTEXT], "codes": [c[1] for c in CONTEXT], "dM": np.column_stack(cols),
            "lag": np.array(lags), "fetched": min(fetched)}


class TokStats:
    """Standardisation of every token from training months only: targets as macro_bayes.Stats, context
    series by their own mean and sd over months 13..last."""

    def __init__(self, st: mb.Stats, ctx: dict, last: int) -> None:
        c = ctx["dM"][13:last + 1]
        self.ym = np.r_[st.ym, np.nanmean(c, 0)]
        self.ys = np.r_[st.ys, np.nanstd(c, 0) + 1e-8]


def tokens(data: dict, ctx: dict, ts: TokStats) -> np.ndarray:
    """Standardised monthly changes of every token [M, targets + context]."""
    return (np.column_stack([data["dM"], ctx["dM"]]) - ts.ym) / ts.ys


def oil_inputs(data: dict, st: mb.Stats) -> tuple[np.ndarray, np.ndarray]:
    """Brent's standardised change at lags 0..12 [M, 13] and the oil volatility state [M]."""
    z = np.nan_to_num(data["oil_m"]) / st.xs
    M = len(z)
    lag = np.stack([np.r_[np.zeros(l), z[:M - l]] for l in range(mb.LAGS)], 1)
    return lag, (mb.log_vol(z) - st.vm) / st.vs


def inputs(own: np.ndarray, oil: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Token inputs [..., T, OWN + 13 + 1 + 1] from own lags [..., T, OWN] (NaN = not observed), oil
    lags [..., 13] and the volatility state [...]: lags, oil, volatility, availability flag."""
    T = own.shape[-2]
    avail = np.isfinite(own[..., :1])
    return np.concatenate([np.nan_to_num(own), np.broadcast_to(oil[..., None, :], own.shape[:-2] + (T, oil.shape[-1])),
                           np.broadcast_to(v[..., None, None], own.shape[:-2] + (T, 1)), avail.astype(float)], -1)


def training_rows(Y: np.ndarray, oil: np.ndarray, v: np.ndarray, last: int):
    """(months, inputs [S, T, F], targets [S, T], mask [S, T]) for months 13..last. A token is
    scored where its change and its previous change are known, as in macro_bayes.design."""
    s = np.arange(13, last + 1)
    own = np.stack([Y[s - l] for l in range(1, OWN + 1)], -1)
    y = Y[s]
    return s, inputs(own, oil[s], v[s]), y, np.isfinite(y) & np.isfinite(own[..., 0])


# --- network ---------------------------------------------------------------------------------

class XAttn(nn.Module):
    """Tokens [B, T, F] -> per-token Student-t (location, scale, tail index), attention across tokens."""

    seq = False

    def __init__(self, n_tok: int, n_in: int, floor: np.ndarray) -> None:
        super().__init__()
        self.emb = nn.Embedding(n_tok, mg.EMB)
        self.proj = nn.Linear(n_in + mg.EMB, D_MODEL)
        layer = nn.TransformerEncoderLayer(D_MODEL, HEADS, 2 * D_MODEL, mg.DROPOUT, batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(layer, LAYERS, enable_nested_tensor=False)
        self.norm, self.head = nn.LayerNorm(D_MODEL), nn.Linear(D_MODEL, 3)
        self.lin = nn.Parameter(torch.zeros(n_tok, n_in))  # per-token linear term, as global_lin
        self.register_buffer("floor", torch.as_tensor(floor, dtype=torch.float32))
        self.register_buffer("tok", torch.arange(n_tok))

    def forward(self, x):
        h = self.proj(torch.cat([x, self.emb(self.tok).expand(len(x), -1, -1)], -1))
        o = self.head(self.norm(self.enc(h)))
        loc = o[..., 0] + (self.lin * x).sum(-1)
        return loc, self.floor + nn.functional.softplus(o[..., 1]), mb.NU_MIN + nn.functional.softplus(o[..., 2])


def nll(net: XAttn, x, y, mask):
    loc, scale, nu = net(x)
    lp = torch.distributions.StudentT(nu, loc, scale).log_prob(torch.nan_to_num(y))
    return -(lp * mask).sum() / mask.sum().clamp(min=1)


def train(x: np.ndarray, y: np.ndarray, mask: np.ndarray, months: np.ndarray, floor: np.ndarray, seed: int) -> tuple[XAttn, dict]:
    """Early stopping on the last quarter of the training months, then a refit on all of them for the
    best epoch count, as macro_global.train."""
    cfg = TRAIN | ({"epochs": 3, "patience": 1} if QUICK else {})
    X, Y, Mk = (torch.as_tensor(a, dtype=torch.float32) for a in (x, y, mask))
    cut = np.quantile(months, 1 - mg.VAL_SHARE)

    def fit(rows: np.ndarray, epochs: int, val: torch.Tensor | None = None) -> tuple[XAttn, float, int]:
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        net = XAttn(x.shape[1], x.shape[2], floor)
        opt = torch.optim.AdamW(net.parameters(), lr=cfg["lr"], weight_decay=cfg["wd"])
        best, best_ep, bad, state = np.inf, epochs, 0, None
        for ep in range(1, epochs + 1):
            net.train()
            for b in np.array_split(rng.permutation(rows), max(1, len(rows) // cfg["batch"])):
                b = torch.from_numpy(b)
                loss = nll(net, X[b], Y[b], Mk[b])
                opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                opt.step()
            if val is None:
                continue
            net.eval()
            with torch.no_grad():
                v = nll(net, X[val], Y[val], Mk[val]).item()
            if v < best - 1e-4:
                best, best_ep, bad, state = v, ep, 0, copy.deepcopy(net.state_dict())
            else:
                bad += 1
                if bad > cfg["patience"]:
                    break
        if state is not None:
            net.load_state_dict(state)
        net.eval()
        return net, best, best_ep

    inner, val = np.flatnonzero(months <= cut), torch.from_numpy(np.flatnonzero(months > cut))
    _, val_nll, best_ep = fit(inner, cfg["epochs"], val)
    net, _, _ = fit(np.arange(len(y)), best_ep)
    return net, {"val_nll": round(val_nll, 4), "best_epoch": best_ep, "months": len(y), "val_months": len(val),
                 "params": sum(p.numel() for p in net.parameters())}


def fit_xattn(data: dict, info: dict, st: mb.Stats, last: int, seeds: int = SEEDS, base_seed: int = 0):
    """Train `seeds` cross-series transformers on months 13..last. Returns (nets, training info, model
    state for simulate)."""
    ctx = context(data)
    ts = TokStats(st, ctx, last)
    oil, v = oil_inputs(data, st)
    months, x, y, mask = training_rows(tokens(data, ctx, ts), oil, v, last)
    floor = np.r_[info["floor"], np.full(len(ctx["keys"]), mb.SIGMA_FLOOR_DEFAULT)]
    fitted = [train(x, y, mask, months, floor, seed=base_seed + SEED_OFFSET + s) for s in range(seeds)]
    return [f[0] for f in fitted], [f[1] for f in fitted], {"ctx": ctx, "ts": ts}


# --- forecasts -------------------------------------------------------------------------------

def simulate(nets: list, state: dict, st: mb.Stats, info: dict, data: dict, t: np.ndarray, future: np.ndarray, rng,
             n: int = mb.DRAWS, noise: bool = True) -> np.ndarray:
    """Draws of every target output (target-major, horizon-minor, as data['names']) at origins t:
    [n, len(t), outputs], as macro_global.simulate with every token stepped forward together. Each
    token starts from its last published month. The targets' surprises are drawn in one standard_t
    call over the K targets, so a copula.CopulaRNG correlates them; the context tokens' are independent."""
    ctx, ts = state["ctx"], state["ts"]
    K, T, O, H = len(info["keys"]), len(info["keys"]) + len(ctx["keys"]), len(t), mn.OIL_AHEAD
    lags = np.r_[info["pub_lag"], ctx["lag"]]
    pmax = int(lags.max())
    z_all = np.nan_to_num(data["oil_m"]) / st.xs
    Y = tokens(data, ctx, ts)
    zf = np.broadcast_to(future / st.xs, (n, O, H))
    s0 = t - pmax + 1
    buf = np.stack([z_all[s0 - 1 - lag] for lag in range(mb.LAGS)], -1)[None].repeat(n, 0)  # [n, O, LAGS]
    own = np.stack([Y[s0 - lag] for lag in range(1, OWN + 1)], -1)[None].repeat(n, 0)  # [n, O, T, OWN]
    which = np.arange(n) % len(nets)
    cum, out = np.zeros((n, O, K)), np.zeros((n, O, K, len(mn.HORIZONS)))
    for j in range(-pmax + 1, H + 1):  # month s = t + j
        znew = zf[:, :, j - 1] if j >= 1 else np.broadcast_to(z_all[t + j], (n, O))
        buf = np.concatenate([znew[..., None], buf[..., :-1]], -1)
        v = (np.log(np.abs(buf[..., :3]).mean(-1) + mb.VOL_FLOOR) - st.vm) / st.vs
        x = inputs(own, buf, v)  # [n, O, T, F]
        m = np.empty((n, O, T))
        for i, net in enumerate(nets):
            sel = which == i
            if not sel.any():
                continue
            with torch.no_grad():
                loc, scale, nu = (a.numpy().astype(float).reshape(-1, O, T)
                                  for a in net(torch.as_tensor(x[sel].reshape(-1, T, x.shape[-1]), dtype=torch.float32)))
            if noise:
                e = np.concatenate([rng.standard_t(nu[..., :K]), rng.standard_t(nu[..., K:])], -1)
                m[sel] = loc + scale * e
            else:
                m[sel] = loc
        known = j <= -lags  # [T]: this month is already published for these tokens
        if known.any():
            obs = Y[t + j]
            m = np.where(known & np.isfinite(obs)[None], np.nan_to_num(obs)[None], m)
        own = np.concatenate([m[..., None], own[..., :-1]], -1)
        if j >= 1:
            cum = cum + m[..., :K] * st.ys + st.ym
            for hi, h in enumerate(mn.HORIZONS):
                if j == h:
                    out[..., hi] = cum
    return out.reshape(n, O, K * len(mn.HORIZONS))


def check() -> None:
    global QUICK
    QUICK = True
    data = mn.make_dataset(mn.V1_BLOCKS)
    _, test, last = mb.fold_window(data, mn.FOLDS - 1)
    st, info = mb.Stats(data, last), mb.series_info(data)
    t0 = time.time()
    nets, training, state = fit_xattn(data, info, st, last, seeds=2)
    S = simulate(nets, state, st, info, data, data["t"][test], data["OIL"][test][None], np.random.default_rng(0), n=50)
    print(f"context {state['ctx']['keys']} (fetched {state['ctx']['fetched']}), training {training}")
    print(f"samples {S.shape}, mean CRPS {np.nanmean(mb.summarise(S, data['Y'][test])['crps']):.4f} ({time.time() - t0:.0f}s)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("check",))
    p.parse_args()
    check()


if __name__ == "__main__":
    main()
