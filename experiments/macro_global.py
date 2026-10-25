# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scipy>=1.11", "xlrd>=2.0", "openpyxl>=3.1", "torch>=2.2",
#                 "jax>=0.4.30", "numpyro>=0.15"]
# ///
"""Global one-step network for the knock-on chain: one network shared by the 22 target series of
experiments/macro_bayes.py, on their monthly changes, simulated forward month by month.

The deep models in macro_nn.py map a 24-month window of 52 inputs straight to 88 multi-horizon
outputs. With 33-174 training origins their validation loss is lowest at epoch 1-2, so they
forecast like climatology. This model asks a smaller question many more times: next month's change
of one series, from

    the series' own last 12 monthly changes, Brent's monthly change at lags 0..12, the oil
    volatility state of macro_bayes.py, and a learned embedding of the series.

Every (month, series) pair is a training row, which gives about 22x more rows, with 26 inputs
instead of 1,248. The head is a Student-t: location, a scale above macro_bayes.py's floor, and a
tail index of at least 2.5. Two variants, fixed before scoring:
    global      the shared network only
    global_lin  plus a per-series linear term in the location (the least-squares momentum and
                oil-lag model nested inside), so the network only has to learn what is shared
A third, added after those two were scored and fixed before its own run, asks whether a TCN works
once it is shared across series and predicts one step ahead (macro_nn.py's windowed TCN did not):
    global_tcn  global_lin with the network's flat inputs replaced by a causal TCN (macro_nn.TCN,
                16 wide, dilations 1, 2, 4, 8) over the last 24 months of the series' own change,
                Brent's change and the volatility state; the TCN's last step and the series
                embedding go into the same MLP and Student-t head, and the per-series linear term
                stays on the 26 flat inputs

Training: AdamW on the Student-t NLL, early stopping on the last quarter of the training months,
then a refit on all of them for the chosen number of epochs. SEEDS networks per variant form a
deep ensemble, and each forecast draw comes from one of them. Forecasts are simulated as in
macro_bayes.py: from each series' last published month, and scored by sample CRPS on the same
forward-chaining folds and training months, in macro_bayes.py's two oil modes:
    whatif    given the oil path that happened (`fold`)
    forecast  nothing after the origin is known (`forecast`): each draw follows its own simulated
              oil path from macro_bayes.oil_paths (block bootstrap of training months, scaled to
              the OVX implied volatility, centred on the WTI futures slope)
The forecast mode is compared with institutional US inflation forecasts (`benchmarks`): the
Cleveland Fed's and Michigan's 1-year expectations and the Philadelphia Fed's Survey of
Professional Forecasters (SPF), each with a Gaussian band from its own training errors.

    uv run experiments/macro_global.py check [--forecast]  # tiny end-to-end run on the last fold
    uv run experiments/macro_global.py fold 3              # what-if -> runs/macro/global-fold-3.json
    uv run experiments/macro_global.py fold 3 --variant global_tcn   # one variant, merged into that file
    uv run experiments/macro_global.py forecast 3          # both modes -> runs/macro/global-forecast-fold-3.json
    uv run experiments/macro_global.py benchmarks          # surveys -> runs/macro/global-benchmarks.json (downloads SPF)
    uv run experiments/macro_global.py report              # notes/macro-global-results.md
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

import macro_bayes as mb
import macro_data as md
import macro_nn as mn

ROOT = Path(__file__).resolve().parent.parent
RUNS, NOTES = ROOT / "runs" / "macro", ROOT / "notes"
OWN = 12  # lags of the series' own monthly change
SEQ = 24  # months of history global_tcn sees
EMB = 8  # series embedding width
HIDDEN, LAYERS, DROPOUT = 64, 2, 0.1
TCN_WIDTH, TCN_LAYERS = 16, 2  # macro_nn.TCN: 2 + TCN_LAYERS blocks, dilations 1, 2, 4, 8
TRAIN = {"epochs": 300, "patience": 30, "lr": 2e-3, "wd": 1e-3, "batch": 256}
VAL_SHARE = 0.25  # last share of training months held out for early stopping
SEEDS = 5
VARIANTS = ("global", "global_lin", "global_tcn")
SHOCK = np.log(1.10)  # +10% Brent in the first month, for the oil response
# Bayesian references for the report: (column, runs/macro file stem). own: each series' own recent
# volatility sets its band (macro_bayes.py --vol own, the main Bayesian model); oil: oil volatility only.
BAYES = (("Bayes own-vol", "bayes-own"), ("Bayes oil-vol", "bayes"))
MAIN = "global_lin"  # the headline variant, chosen on what-if skill before the forecast mode was scored
# Variants the forecast mode runs by default: global_tcn did not beat global_lin on what-if skill
# (add it with `forecast <fold> --variant global_tcn`)
FORECAST_VARIANTS = ("global", "global_lin")
FORECAST_SEED = 700  # forecast mode: rng seed (+ fold) of the oil paths and noise, the same for both variants
SPF = "https://www.philadelphiafed.org/-/media/frbp/assets/surveys-and-data/survey-of-professional-forecasters/"
# Institutional US CPI benchmarks of the forecast mode (key in runs/macro/global-benchmarks.json, label)
INSTITUTIONS = (("cleveland", "Cleveland Fed 1-year expected inflation (FRED EXPINF1YR)"),
                ("michigan", "Michigan 1-year expectations (FRED MICH)"),
                ("spf", "SPF median, at the end of each release month"),
                ("spf_mean", "SPF mean, at the end of each release month"),
                ("spf_latest", "SPF median, latest survey at every month-end"),
                ("rw", "Random walk: last 12-month pace carries on"))
QUICK = False


# --- data ------------------------------------------------------------------------------------

def lagged(a: np.ndarray, lags: range, fill: float) -> np.ndarray:
    """a[s - lag] for each lag, stacked on a new last axis; `fill` before the first month."""
    return np.stack([np.concatenate([np.full((lag,) + a.shape[1:], fill), a[:len(a) - lag]]) for lag in lags], -1)


def features(data: dict, st: mb.Stats) -> dict:
    """Monthly arrays in standardised units, lags newest first: own lags [M, K, SEQ] (y[s-1..s-24]),
    oil lags [M, SEQ] (z[s..s-23]), volatility state v [M] and its lags [M, SEQ] (v[s..s-23]), and
    targets y [M, K]. The flat inputs take the first OWN own lags, the first LAGS oil lags and v[s]."""
    z = np.nan_to_num(data["oil_m"]) / st.xs
    y = (data["dM"] - st.ym) / st.ys
    v = (mb.log_vol(z) - st.vm) / st.vs
    return {"own": lagged(y, range(1, SEQ + 1), np.nan), "oil": lagged(z, range(SEQ), 0.0), "v": v,
            "vol": lagged(v, range(SEQ), 0.0), "y": y}


def training_rows(f: dict, last_month: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(month, series, inputs, target) for months 13..last_month where the target and the previous
    month are known, as in macro_bayes.design. Older missing own lags read as 0 (the mean)."""
    s, k = np.meshgrid(np.arange(13, last_month + 1), np.arange(f["y"].shape[1]), indexing="ij")
    ok = np.isfinite(f["y"][s, k]) & np.isfinite(f["own"][s, k, 0])
    s, k = s[ok], k[ok]
    x = np.concatenate([np.nan_to_num(f["own"][s, k, :OWN]), f["oil"][s, :mb.LAGS], f["vol"][s, :1]], 1)
    return s, k, x, f["y"][s, k]


def seq_inputs(own: np.ndarray, oil: np.ndarray, vol: np.ndarray) -> np.ndarray:
    """global_tcn's input from newest-first lags [..., SEQ] (own lags 1..24, oil and volatility lags
    0..23, broadcast together): [..., SEQ, 3], oldest month first. The last step is month s, with
    the series' own change a month earlier, and Brent's change and the volatility state in s."""
    return np.ascontiguousarray(np.stack(np.broadcast_arrays(own, oil, vol), -1)[..., ::-1, :])


def sequences(f: dict, s: np.ndarray, k: np.ndarray) -> np.ndarray:
    """global_tcn's input [rows, SEQ, 3] for training rows (s, k); missing own lags read as 0."""
    return seq_inputs(np.nan_to_num(f["own"][s, k]), f["oil"][s], f["vol"][s])


# --- network ---------------------------------------------------------------------------------

class Net(nn.Module):
    """Shared MLP on [inputs, series embedding] -> Student-t (location, scale, tail index)."""

    seq = False  # forward(x, k) only; SeqNet also takes the 24-month sequences

    def __init__(self, n_series: int, n_in: int, floor: np.ndarray, linear: bool, n_body: int | None = None) -> None:
        super().__init__()
        self.emb = nn.Embedding(n_series, EMB)
        layers, d = [], (n_in if n_body is None else n_body) + EMB
        for _ in range(LAYERS):
            layers += [nn.Linear(d, HIDDEN), nn.GELU(), nn.Dropout(DROPOUT)]
            d = HIDDEN
        self.body, self.head = nn.Sequential(*layers), nn.Linear(d, 3)
        # global_lin: a per-series linear term in the location, i.e. momentum and oil lags per series
        self.lin = nn.Parameter(torch.zeros(n_series, n_in)) if linear else None
        self.register_buffer("floor", torch.as_tensor(floor, dtype=torch.float32))

    def forward(self, x, k):
        return self.student_t(torch.cat([x, self.emb(k)], -1), x, k)

    def student_t(self, z, x, k):
        """The MLP on z, plus the linear term on the flat inputs x, as Student-t parameters."""
        h = self.head(self.body(z))
        loc = h[:, 0] + ((self.lin[k] * x).sum(-1) if self.lin is not None else 0.0)
        scale = self.floor[k] + nn.functional.softplus(h[:, 1])
        return loc, scale, mb.NU_MIN + nn.functional.softplus(h[:, 2])


class SeqNet(Net):
    """global_tcn: a causal TCN over the 24-month sequences [B, SEQ, 3] in place of the flat inputs.
    Its last step (month s) and the series embedding go into Net's MLP and Student-t head; the
    per-series linear term stays on the flat inputs."""

    seq = True

    def __init__(self, n_series: int, n_in: int, floor: np.ndarray, linear: bool) -> None:
        super().__init__(n_series, n_in, floor, linear, n_body=TCN_WIDTH)
        self.tcn = mn.TCN(3, TCN_WIDTH, TCN_LAYERS, DROPOUT)

    def forward(self, x, k, seq):
        return self.student_t(torch.cat([self.tcn(seq), self.emb(k)], -1), x, k)


class OLS(nn.Module):
    """Per-series least squares on the network's inputs, Gaussian errors at the residual sd above the
    same floor: the inputs without the network, to tell their gain from the network's."""

    def __init__(self, x: np.ndarray, k: np.ndarray, y: np.ndarray, floor: np.ndarray) -> None:
        super().__init__()
        K = len(floor)
        W, sd = np.zeros((K, x.shape[1] + 1)), np.ones(K)
        for kk in range(K):
            if (k == kk).sum() <= x.shape[1] + 1:  # too few months to fit (a late-starting sector series)
                continue
            A = np.column_stack([x[k == kk], np.ones((k == kk).sum())])
            W[kk], *_ = np.linalg.lstsq(A, y[k == kk], rcond=None)
            sd[kk] = max((y[k == kk] - A @ W[kk]).std(), floor[kk])
        self.W, self.sd = torch.as_tensor(W, dtype=torch.float32), torch.as_tensor(sd, dtype=torch.float32)

    def forward(self, x, k):
        return (x * self.W[k, :-1]).sum(-1) + self.W[k, -1], self.sd[k], torch.full((len(x),), 1e6)


def nll(net: Net, x, k, y, seq=None):
    loc, scale, nu = net(x, k) if seq is None else net(x, k, seq)
    return -torch.distributions.StudentT(nu, loc, scale).log_prob(y).mean()


def train(x: np.ndarray, k: np.ndarray, y: np.ndarray, months: np.ndarray, floor: np.ndarray, linear: bool,
          seed: int, seq: np.ndarray | None = None) -> tuple[Net, dict]:
    """Early stopping on the last VAL_SHARE of the training months, then a refit on all of them for
    the best epoch count (so the latest months, the closest to the test block, are used). With seq
    (the rows' 24-month sequences, from `sequences`) the network is global_tcn's SeqNet."""
    cfg = TRAIN | ({"epochs": 3, "patience": 1} if QUICK else {})
    X, K, Y = (torch.as_tensor(x, dtype=torch.float32), torch.as_tensor(k, dtype=torch.long),
               torch.as_tensor(y, dtype=torch.float32))
    S = None if seq is None else torch.as_tensor(seq, dtype=torch.float32)
    cut = np.quantile(np.unique(months), 1 - VAL_SHARE)
    n_series = len(floor)  # every series, including any without training rows yet

    def fit(rows: np.ndarray, epochs: int, val: np.ndarray | None = None) -> tuple[Net, float, int]:
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        net = Net(n_series, x.shape[1], floor, linear) if S is None else SeqNet(n_series, x.shape[1], floor, linear)
        opt = torch.optim.AdamW(net.parameters(), lr=cfg["lr"], weight_decay=cfg["wd"])
        best, best_ep, bad, state = np.inf, epochs, 0, None
        for ep in range(1, epochs + 1):
            net.train()
            for b in np.array_split(rng.permutation(rows), max(1, len(rows) // cfg["batch"])):
                b = torch.from_numpy(b)
                loss = nll(net, X[b], K[b], Y[b], None if S is None else S[b])
                opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                opt.step()
            if val is None:
                continue
            net.eval()
            with torch.no_grad():
                v = nll(net, X[val], K[val], Y[val], None if S is None else S[val]).item()
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
    return net, {"val_nll": round(val_nll, 4), "best_epoch": best_ep, "rows": len(y), "val_rows": len(val)}


def fit_nets(data: dict, info: dict, st: mb.Stats, last: int, variant: str, seeds: int = SEEDS,
             base_seed: int = 0) -> tuple[list, list[dict]]:
    """Build the training rows for months 13..last and train `seeds` networks of `variant`
    ("global", "global_lin" or "global_tcn"). Returns (nets, per-seed training info). Network s
    gets seed base_seed + 100 * VARIANTS.index(variant) + s (run_fold passes base_seed = 1000 * fold)."""
    f = features(data, st)
    months, k, x, y = training_rows(f, last)
    seq = sequences(f, months, k) if variant == "global_tcn" else None
    vi = VARIANTS.index(variant)
    fitted = [train(x, k, y, months, info["floor"], variant != "global", seed=base_seed + 100 * vi + s, seq=seq)
              for s in range(seeds)]
    return [net for net, _ in fitted], [tr for _, tr in fitted]


# --- forecasts -------------------------------------------------------------------------------

def simulate(nets: list, st: mb.Stats, info: dict, data: dict, t: np.ndarray, future: np.ndarray, rng,
             n: int = mb.DRAWS, noise: bool = True) -> np.ndarray:
    """Draws of every output (target-major, horizon-minor, as data['names']) at origins t (month
    indices): [n, len(t), outputs], as macro_bayes.simulate with the next month's Student-t from
    the networks. Draw i comes from nets[i % len(nets)]; a net with seq = True (SeqNet) also gets the
    24-month sequences. noise=False follows the location only."""
    K, O, pmax, H = len(info["keys"]), len(t), int(info["pub_lag"].max()), mn.OIL_AHEAD
    z_all = np.nan_to_num(data["oil_m"]) / st.xs
    v_all = (mb.log_vol(z_all) - st.vm) / st.vs
    y_all = (data["dM"] - st.ym) / st.ys
    zf = np.broadcast_to(future / st.xs, (n, O, H))
    s0 = t - pmax + 1  # first simulated month: every series is published up to s0 - 1
    # SEQ-month buffers, newest first: oil and volatility lags 0..23 of month s0 - 1, own lags 1..24 of
    # month s0. The flat inputs read the first LAGS oil and OWN own lags, as before.
    buf = np.stack([z_all[s0 - 1 - lag] for lag in range(SEQ)], -1)[None].repeat(n, 0)  # [n, O, SEQ]
    vol = np.stack([v_all[s0 - 1 - lag] for lag in range(SEQ)], -1)[None].repeat(n, 0)  # [n, O, SEQ]
    own = np.stack([np.nan_to_num(y_all[s0 - lag]) for lag in range(1, SEQ + 1)], -1)[None].repeat(n, 0)  # [n, O, K, SEQ]
    which = np.arange(n) % len(nets)
    cum = np.zeros((n, O, K))
    out = np.zeros((n, O, K, len(mn.HORIZONS)))
    for j in range(-pmax + 1, H + 1):  # month s = t + j
        znew = zf[:, :, j - 1] if j >= 1 else np.broadcast_to(z_all[t + j], (n, O))
        buf = np.concatenate([znew[..., None], buf[..., :-1]], -1)
        v = (np.log(np.abs(buf[..., :3]).mean(-1) + mb.VOL_FLOOR) - st.vm) / st.vs  # [n, O]
        vol = np.concatenate([v[..., None], vol[..., :-1]], -1)
        x = np.concatenate([own[..., :OWN], np.broadcast_to(buf[:, :, None, :mb.LAGS], (n, O, K, mb.LAGS)),
                            np.broadcast_to(v[:, :, None, None], (n, O, K, 1))], -1)
        m = np.empty((n, O, K))
        for i, net in enumerate(nets):
            sel = which == i
            if not sel.any():
                continue
            xi = torch.as_tensor(x[sel].reshape(-1, x.shape[-1]), dtype=torch.float32)
            ki = torch.as_tensor(np.tile(np.arange(K), int(sel.sum()) * O))  # series index, fastest-varying
            args = (xi, ki)
            if getattr(net, "seq", False):
                si = seq_inputs(own[sel], buf[sel][:, :, None], vol[sel][:, :, None])  # [draws, O, K, SEQ, 3]
                args += (torch.as_tensor(si.reshape(-1, SEQ, 3), dtype=torch.float32),)
            with torch.no_grad():
                loc, scale, nu = (a.numpy().astype(float).reshape(-1, O, K) for a in net(*args))
            m[sel] = loc + scale * rng.standard_t(nu) if noise else loc
        known = j <= -info["pub_lag"]  # [K]: this month is already published for these series
        if known.any():
            obs = y_all[t + j]
            m = np.where(known & np.isfinite(obs)[None], np.nan_to_num(obs)[None], m)
        own = np.concatenate([m[..., None], own[..., :-1]], -1)
        if j >= 1:
            cum = cum + m * st.ys + st.ym
            for hi, h in enumerate(mn.HORIZONS):
                if j == h:
                    out[..., hi] = cum
    return out.reshape(n, O, K * len(mn.HORIZONS))


def run_fold(data: dict, j: int, variants: tuple = VARIANTS) -> dict:
    dates = data["dates"]
    train_idx, test, last = mb.fold_window(data, j)
    info, st = mb.series_info(data), mb.Stats(data, last)
    rows = len(training_rows(features(data, st), last)[3])
    print(f"fold {j}: train months to {last} ({rows} rows), test {dates[test[0]]:%Y-%m}..{dates[test[-1]]:%Y-%m}",
          flush=True)
    t, Y, oil = data["t"][test], data["Y"][test], data["OIL"][test]
    shocked = oil.copy()
    shocked[:, 0] += SHOCK
    out = {"fold": j, "test_dates": [f"{d:%Y-%m}" for d in dates[test]], "names": data["names"],
           "groups": data["groups"], "y": Y.tolist(), "train_months_to": int(last), "models": {}}
    for variant in variants:  # seeds depend on the variant and fold, not on which others run
        t0 = time.time()
        nets, training = fit_nets(data, info, st, last, variant, 2 if QUICK else SEEDS, base_seed=1000 * j)
        S = simulate(nets, st, info, data, t, oil[None], np.random.default_rng(300 + j))
        # oil response: location-only paths with and without the shock, averaged over origins and networks
        base = simulate(nets, st, info, data, t, oil[None], None, n=len(nets), noise=False)
        up = simulate(nets, st, info, data, t, shocked[None], None, n=len(nets), noise=False)
        out["models"][variant] = mb.summarise(S, Y) | {
            "training": training, "seconds": round(time.time() - t0, 1),
            "response_up10": (up - base).mean((0, 1)).tolist()}
        ep = [tr["best_epoch"] for tr in training]
        print(f"  {variant}: best epochs {ep}, CRPS {np.nanmean(out['models'][variant]['crps']):.4f} "
              f"({time.time() - t0:.0f}s)", flush=True)
    return out


def run_ols() -> dict:
    """The OLS benchmark on every fold (no training loop, so all folds in one go)."""
    data = mn.make_dataset(mn.V1_BLOCKS)
    folds = []
    for j in range(mn.FOLDS):
        _, test, last = mb.fold_window(data, j)
        info, st = mb.series_info(data), mb.Stats(data, last)
        months, k, x, y = training_rows(features(data, st), last)
        S = simulate([OLS(x, k, y, info["floor"])], st, info, data, data["t"][test], data["OIL"][test][None],
                     np.random.default_rng(500 + j))
        folds.append({"fold": j, "test_dates": [f"{d:%Y-%m}" for d in data["dates"][test]]}
                     | mb.summarise(S, data["Y"][test]))
        print(f"ols fold {j}: CRPS {np.nanmean(folds[-1]['crps']):.4f}", flush=True)
    return {"folds": folds}


# --- forecast mode ---------------------------------------------------------------------------

def run_forecast_fold(data: dict, j: int, market: dict, variants: tuple = FORECAST_VARIANTS) -> dict:
    """Fold j in both oil modes, as macro_bayes.run_fold. The networks are run_fold's (fit_nets, same
    seeds and training), so `whatif` repeats runs/macro/global-fold-{j}.json. `forecast` knows
    nothing after the origin: draw i follows simulated oil path i from macro_bayes.oil_paths, and
    every variant gets the same paths and noise draws (FORECAST_SEED)."""
    dates = data["dates"]
    _, test, last = mb.fold_window(data, j)
    info, st = mb.series_info(data), mb.Stats(data, last)
    rows = len(training_rows(features(data, st), last)[3])
    print(f"forecast fold {j}: train months to {last} ({rows} rows), test "
          f"{dates[test[0]]:%Y-%m}..{dates[test[-1]]:%Y-%m}", flush=True)
    t, Y = data["t"][test], data["Y"][test]
    out = {"fold": j, "test_dates": [f"{d:%Y-%m}" for d in dates[test]], "names": data["names"],
           "groups": data["groups"], "y": Y.tolist(), "train_months_to": int(last),
           "market": {"origins_with_futures": int(market["has_futures"][t].sum()),
                      "origins_with_ovx": int(np.isfinite(market["ovx"][t]).sum()), "fetched": market["fetched"]},
           "models": {}}
    for variant in variants:
        t0 = time.time()
        nets, training = fit_nets(data, info, st, last, variant, 2 if QUICK else SEEDS, base_seed=1000 * j)
        whatif = simulate(nets, st, info, data, t, data["OIL"][test][None], np.random.default_rng(300 + j))
        rng = np.random.default_rng(FORECAST_SEED + j)
        fut = mb.oil_paths(data, st, last, t, mb.DRAWS, rng, market)
        modes = {"whatif": mb.summarise(whatif, Y), "forecast": mb.summarise(simulate(nets, st, info, data, t, fut, rng), Y)}
        out["models"][variant] = {"modes": modes, "training": training, "seconds": round(time.time() - t0, 1)}
        print(f"  {variant}: best epochs {[tr['best_epoch'] for tr in training]}, CRPS what-if "
              f"{np.nanmean(modes['whatif']['crps']):.4f}, forecast {np.nanmean(modes['forecast']['crps']):.4f} "
              f"({time.time() - t0:.0f}s)", flush=True)
    return out


# --- institutional US inflation forecasts ----------------------------------------------------

def parse_release_dates(text: str) -> pd.DataFrame:
    """The SPF's deadline and news release dates file: one row per survey (YEAR, QUARTER, released).
    The year is written only on each year's first line; surveys without a release date are left out."""
    rows, year = [], None
    for line in text.splitlines():
        m = re.match(r"\s*(\d{4})?\s*Q([1-4])\s+(\d+/\d+/\d+)\**\s*(\d+/\d+/\d+)?", line)
        if not m:
            continue
        year = int(m[1]) if m[1] else year
        if year is not None and m[4]:
            rows.append((year, int(m[2]), pd.to_datetime(m[4], format="%m/%d/%y")))
    return pd.DataFrame(rows, columns=["YEAR", "QUARTER", "released"])


def fetch_spf(stat: str = "median") -> pd.DataFrame:
    """Survey of Professional Forecasters (Philadelphia Fed), headline CPI, one row per survey:
    YEAR, QUARTER, CPI1..CPI6 (annualised % change of the quarterly average CPI over the previous
    quarter: CPI1 the quarter before the survey's (history), CPI2 the survey quarter, CPI3..CPI6
    the next four), and its news release date. stat: median or mean across forecasters."""
    p = md._get(SPF + f"data-files/files/{stat}_cpi_level.xlsx", md.RAW / f"spf_{stat}_cpi_level.xlsx")
    rel = md._get(SPF + "spf-release-dates.txt", md.RAW / "spf_release_dates.txt")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # openpyxl cannot parse the sheet's print header
        df = pd.read_excel(p)
    return df.merge(parse_release_dates(rel.read_text(encoding="utf-8", errors="replace")), on=["YEAR", "QUARTER"])


def spf_match(dates: pd.DatetimeIndex, surveys: pd.DataFrame, latest: bool) -> tuple[np.ndarray, np.ndarray]:
    """For each origin (the end of month dates[i]): the row of `surveys` it uses (-1 for none) and m,
    the months from the middle month of that survey's quarter to the origin. A survey counts as
    public at the end of the month of its news release (mid-Feb, May, Aug, Nov; the 2013Q4, 2019Q1
    and 2026Q1 surveys came late). latest=False: a survey is used only at the end of its release
    month; latest=True: every origin uses the latest survey public by then."""
    rel = surveys["released"].dt.year.to_numpy() * 12 + surveys["released"].dt.month.to_numpy()
    order = surveys["YEAR"].to_numpy() * 4 + surveys["QUARTER"].to_numpy()
    mid = surveys["YEAR"].to_numpy() * 12 + 3 * surveys["QUARTER"].to_numpy() - 1  # Feb, May, Aug, Nov
    row, m = np.full(len(dates), -1), np.zeros(len(dates), int)
    for i, d in enumerate(pd.DatetimeIndex(dates)):
        now = d.year * 12 + d.month
        public = np.flatnonzero(rel <= now)
        if not len(public):
            continue
        r = public[np.argmax(order[public])]
        if latest or rel[r] == now:
            row[i], m[i] = r, now - mid[r]
    return row, m


def spf_change(g: np.ndarray, m: np.ndarray, h: int) -> np.ndarray:
    """Change in 100 x log CPI over the h months after an origin m months past the middle of survey
    quarter q, from the survey's path [n, 4]: g = 100 x log growth of the quarterly average CPI in
    quarters q+1..q+4 (CPI3..CPI6, de-annualised). Each quarter's average stands for its middle
    month and the log level is linear in between, so month u after the middle of quarter q grows
    by g[ceil(u / 3)] / 3; past quarter q+4 its rate carries on. For m = 0 and h = 12 this is the
    survey's 4-quarter change, quarter q to q+4, which is centred on the 12 months after the origin."""
    u = m[:, None] + np.arange(1, h + 1)[None]
    return np.take_along_axis(g, np.clip((u + 2) // 3, 1, 4) - 1, 1).sum(1) / 3


def spf_forecasts(dates: pd.DatetimeIndex, surveys: pd.DataFrame, latest: bool) -> np.ndarray:
    """SPF forecasts of the change in 100 x log US CPI over each of mn.HORIZONS after each origin
    [len(dates), len(HORIZONS)], NaN where no survey applies (see spf_match and spf_change)."""
    surveys = surveys.dropna(subset=["CPI3", "CPI4", "CPI5", "CPI6", "released"]).reset_index(drop=True)
    row, m = spf_match(dates, surveys, latest)
    g = 100 * np.log1p(surveys[["CPI3", "CPI4", "CPI5", "CPI6"]].to_numpy(float) / 100) / 4
    out, ok = np.full((len(dates), len(mn.HORIZONS)), np.nan), row >= 0
    for hi, h in enumerate(mn.HORIZONS):
        out[ok, hi] = spf_change(g[row[ok]], m[ok], h)
    return out


def gauss_crps(Y: np.ndarray, F: np.ndarray, train: np.ndarray, test: np.ndarray) -> np.ndarray:
    """CRPS [test, outputs] of point forecasts F with a Gaussian band whose sd, per output, is that
    of their errors on the training origins (as macro_bayes.run_benchmarks); NaN where F is."""
    with warnings.catch_warnings(), np.errstate(invalid="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)  # outputs a benchmark does not forecast
        sd = np.nanstd(Y[train] - F[train], 0)
        ok = np.isfinite(Y[test]) & np.isfinite(F[test]) & (sd > 0)
        return np.where(ok, mb.gaussian_crps(F[test], sd, Y[test]), np.nan)


def run_benchmarks(data: dict) -> dict:
    """Per fold, CRPS and point forecast [origins, outputs] of the forecast-mode inflation
    benchmarks (NaN for outputs they do not forecast):
      rw          every inflation series runs at its last published 12-month pace (all horizons)
      cleveland   US CPI: Cleveland Fed 1-year expected inflation (FRED EXPINF1YR), month t's value
                  at the end of month t, as an annual rate (x h/12 at horizon h)
      michigan    US CPI: Michigan 1-year expectations (FRED MICH), the same way
      spf         US CPI: SPF median, at the end of each survey's release month only
      spf_mean    the same with the SPF mean
      spf_latest  US CPI: SPF median at every origin, from the latest survey public by then
    rw, cleveland and michigan at 12 months are macro_bayes.run_benchmarks'."""
    names, Y, t_all, dates = data["names"], data["Y"], data["t"], data["dates"]
    info, idx = mb.series_info(data), mb.month_index(data)
    reg = {s.key: s for s in md.registry(md.BLOCKS)}
    nh, hor = len(mn.HORIZONS), np.array(mn.HORIZONS)
    us = [names.index(f"us_cpi@{h}") for h in mn.HORIZONS]
    P = {k: np.full(Y.shape, np.nan) for k, _ in INSTITUTIONS}
    for kk, key in enumerate(info["keys"]):
        if reg[key].target == "inflation":
            p = reg[key].lag
            pace = np.array([np.nansum(data["dM"][i - p - 11:i - p + 1, kk]) for i in t_all])
            P["rw"][:, kk * nh:(kk + 1) * nh] = pace[:, None] * hor[None] / 12
    for k, code in (("cleveland", "EXPINF1YR"), ("michigan", "MICH")):
        P[k][:, us] = 100 * np.log1p(md.fetch_fred(code).reindex(idx).values[t_all, None] / 100) * hor[None] / 12
    spf = {stat: fetch_spf(stat) for stat in ("median", "mean")}
    for k, stat, latest in (("spf", "median", False), ("spf_mean", "mean", False), ("spf_latest", "median", True)):
        P[k][:, us] = spf_forecasts(dates, spf[stat], latest)
    folds = []
    for j in range(mn.FOLDS):
        train, test, _ = mb.fold_window(data, j)
        folds.append({"fold": j, "test_dates": [f"{d:%Y-%m}" for d in dates[test]], "names": names,
                      "crps": {k: gauss_crps(Y, F, train, test).tolist() for k, F in P.items()},
                      "mu": {k: F[test].tolist() for k, F in P.items()}})
    files = [md.RAW / n for n in ("spf_median_cpi_level.xlsx", "spf_mean_cpi_level.xlsx", "spf_release_dates.txt",
                                  "fred_EXPINF1YR.csv", "fred_MICH.csv")]
    fetched = min(datetime.fromtimestamp(f.stat().st_mtime, UTC).date().isoformat() for f in files)
    last = spf["median"].dropna(subset=["CPI6"]).iloc[-1]
    return {"folds": folds, "fetched": fetched, "spf_last_survey": f"{int(last['YEAR'])}Q{int(last['QUARTER'])}",
            "sources": {"cleveland": "FRED EXPINF1YR", "michigan": "FRED MICH",
                        "spf": SPF + "data-files/files/{median,mean}_cpi_level.xlsx and spf-release-dates.txt"}}


# --- report ----------------------------------------------------------------------------------

def report() -> None:
    folds = []
    for j in range(mn.FOLDS):
        g, v = mb.load(f"global-fold-{j}.json"), mb.load(f"fold-{j}.json")
        if not (g and v):
            continue
        b = {tag: mb.load(f"{tag}-fold-{j}.json") for _, tag in BAYES}
        a = mb.load(f"fold-anchored-{j}.json")
        others = [(v, f"fold-{j}"), (a, f"fold-anchored-{j}")] + [(b[tag], f"{tag}-fold-{j}") for _, tag in BAYES]
        for other, label in others:
            if other is None:
                continue
            assert other["test_dates"] == g["test_dates"] and other["names"] == g["names"], f"{label}: origins or outputs differ"
            assert np.allclose(np.array(other["y"], float), np.array(g["y"], float), equal_nan=True), f"{label}: targets differ"
        folds.append({"g": g, "v1": v, "bayes": b, "anch": a})
    if not folds:
        raise SystemExit("no runs/macro/global-fold-*.json yet")
    ols = mb.load("global-ols.json")
    ols = {f["fold"]: f for f in ols["folds"]} if ols else {}
    for f in folds:
        f["ols"] = ols.get(f["g"]["fold"])
        if f["ols"]:
            assert f["ols"]["test_dates"] == f["g"]["test_dates"], f"global-ols fold {f['g']['fold']}: origins differ"
    has_ols = all(f["ols"] for f in folds)
    names, groups = folds[0]["g"]["names"], np.array(folds[0]["g"]["groups"])
    H = np.array([int(n.split("@")[1]) for n in names])
    refs = [(col, tag) for col, tag in BAYES
            if all(f["bayes"][tag] and mb.converged(f["bayes"][tag]["diagnostics"]) for f in folds)]
    has_anch = all(f["anch"] for f in folds)
    variants = [m for m in VARIANTS if all(m in f["g"]["models"] for f in folds)]

    def stack(get):
        return np.vstack([np.array(get(f), float) for f in folds])

    scale = np.nanmean(stack(lambda f: f["v1"]["models"]["climatology"]["crps"]), 0)
    C = {name: stack(lambda f, m=name: f["g"]["models"][m]["crps"]) for name in variants}
    if has_ols:
        C["OLS, same inputs"] = stack(lambda f: f["ols"]["crps"])
    for col, tag in refs:
        C[col] = stack(lambda f, tag=tag: f["bayes"][tag]["modes"]["whatif"]["crps"])
    if has_anch:
        C["anchored nn_mean"] = stack(lambda f: f["anch"]["models"]["nn_mean"]["crps"])
    C["v1 nn_mean"] = stack(lambda f: f["v1"]["models"]["nn_mean"]["crps"])

    def cols(grp, h="all"):
        return np.where((groups == grp) & ((H == h) if h != "all" else True))[0]

    def skill(M, c):
        return 1 - np.nanmean(np.nanmean(M[:, c], 0) / scale[c])

    first, last = folds[0]["g"]["test_dates"][0], folds[-1]["g"]["test_dates"][-1]
    n_orig = sum(len(f["g"]["test_dates"]) for f in folds)
    when = {tag: sorted(f["bayes"][tag]["meta"]["generated"] for f in folds if "meta" in f["bayes"][tag])
            for _, tag in refs}
    ran = {}  # (first, last) run date -> variants; a variant run on its own (--variant) carries its own meta
    for m in variants:
        w = sorted(f["g"]["models"][m].get("meta", f["g"]["meta"])["generated"] for f in folds)
        ran.setdefault((w[0], w[-1]), []).append(f"`{m}`")
    out = [
        "# Global one-step network: results", "",
        f"_Generated by `experiments/macro_global.py report` on {datetime.now(UTC).date().isoformat()} from "
        f"{len(folds)} forward-chaining folds ({first}..{last}, {n_orig} forecast origins), the same folds, "
        "training months and data as `notes/macro-bayes-results.md` (inputs: `notes/macro-panel.md`). The data are "
        "real and revised (not real-time vintages); nothing is synthetic. The forecasts in the first sections are "
        "**what-ifs**: they are given the oil path that happened. The forecast-mode sections at the end know nothing "
        "after the origin and are compared with institutional US inflation forecasts."
        + "".join(f" {', '.join(ms)} in `runs/macro/global-fold-*.json` generated {a} to {b}." for (a, b), ms in ran.items())
        + "".join(f" `runs/macro/{tag}-fold-*.json` generated {w[0]} to {w[-1]}." for tag, w in when.items() if w)
        + "_", "",
        "Skill = 1 − CRPS / CRPS of the v1 climatology (training mean and spread), averaged over the outputs in "
        "the group; 0 is no better than climatology. `global` is one network shared by all 22 series; "
        "`global_lin` adds a per-series linear term (momentum and oil lags) to its location. "
        + ("`global_tcn` (added after the first two were scored) keeps that linear term but replaces the "
           "network's flat inputs with a causal TCN (16 wide, dilations 1, 2, 4, 8) over the last 24 months of the "
           "series' own change, Brent's change and the volatility state, shared by all series and predicting one "
           "month ahead like the others. " if "global_tcn" in variants else "")
        + "`OLS, same inputs` "
        "is per-series least squares on the networks' inputs (12 own lags, oil lags 0–12, volatility state) with "
        "Gaussian errors, simulated the same way: the inputs without the network. `Bayes own-vol` is the main "
        "Bayesian model (`macro_bayes.py --vol own`: each series' own recent volatility sets its band); "
        "`Bayes oil-vol` lets the band follow oil volatility only (`--vol oil`).", ""]
    for col, tag in BAYES:
        if (col, tag) not in refs:
            out += [f"**No {col} column:** `runs/macro/{tag}-fold-*.json` is missing or not converged for some folds.", ""]
    out += ["## Skill by horizon", "", "| Target | h | " + " | ".join(C) + " |", "|---|---|" + "---|" * len(C)]
    for grp in mb.GROUPS:
        for h in [*mn.HORIZONS, "all"]:
            b = "**" if h == "all" else ""
            out.append(f"| {grp} | {h} | " + " | ".join(f"{b}{skill(M, cols(grp, h)):+.3f}{b}" for M in C.values()) + " |")

    y_all = stack(lambda f: f["g"]["y"])
    runs = [(m, lambda f, m=m: f["g"]["models"][m]) for m in variants]
    runs += [(col, lambda f, tag=tag: f["bayes"][tag]["modes"]["whatif"]) for col, tag in refs]
    out += ["", "## Calibration: share of outcomes inside the central 90% interval (target 90%)", "",
            "| Target | " + " | ".join(r[0] for r in runs) + " |", "|---|" + "---|" * len(runs)]
    for grp in mb.GROUPS:
        c = cols(grp)
        ok = np.isfinite(y_all[:, c])
        cells = []
        for _, get in runs:
            lo, hi = stack(lambda f: get(f)["q05"]), stack(lambda f: get(f)["q95"])
            cells.append(f"{np.mean(((y_all[:, c] >= lo[:, c]) & (y_all[:, c] <= hi[:, c]))[ok]):.0%}")
        out.append(f"| {grp} | " + " | ".join(cells) + " |")

    pairs = [(m, col) for col, _ in refs for m in variants] \
        + [(a, b) for a, b in (("global_lin", "global"), ("global_tcn", "global_lin"), ("global_tcn", "global"))
           if a in variants and b in variants] \
        + [(m, "OLS, same inputs") for m in variants if has_ols] \
        + [("OLS, same inputs", col) for col, _ in refs if has_ols] + [(m, "v1 nn_mean") for m in variants]
    out += ["", "## Are the differences real? Diebold–Mariano tests", "",
            "Mean difference in climatology-scaled CRPS over all horizons (negative: the first model is better), "
            "with its Newey–West t-statistic (12 lags, for the overlapping 12-month targets). |t| > 2 is roughly "
            "significant at 5%.", "",
            "| Comparison | " + " | ".join(mb.GROUPS) + " |", "|---|" + "---|" * len(mb.GROUPS)]
    for m1, m2 in pairs:
        cells = []
        for grp in mb.GROUPS:
            c = cols(grp)
            d = np.nanmean((C[m1][:, c] - C[m2][:, c]) / scale[c], 1)
            cells.append(f"{np.nanmean(d):+.3f} (t {mb.nw_t(d):+.1f})")
        out.append(f"| {m1} vs {m2} | " + " | ".join(cells) + " |")

    if "global_tcn" in variants and "global_lin" in variants:
        others = ["global_lin"] + [col for col, _ in refs[:1]]  # and the main Bayesian model

        def dm(m1, m2, grp):
            c = cols(grp)
            d = np.nanmean((C[m1][:, c] - C[m2][:, c]) / scale[c], 1)
            return float(np.nanmean(d)), mb.nw_t(d)

        tests = {(m, grp): dm("global_tcn", m, grp) for m in others for grp in mb.GROUPS}
        out += ["", "## Does the shared TCN help?", "",
                "`global_tcn` is `global_lin` with its network's flat inputs replaced by the 24-month causal TCN, so "
                "the comparison with `global_lin` isolates the encoder. Skill over all horizons; t is the "
                "Diebold–Mariano t of `global_tcn` minus the other model (positive: `global_tcn` is worse).", "",
                "| Target | global_tcn | " + " | ".join(f"{m} | t vs {m}" for m in others) + " |",
                "|---|---|" + "---|---|" * len(others)]
        for grp in mb.GROUPS:
            c = cols(grp)
            out.append(f"| {grp} | {skill(C['global_tcn'], c):+.3f} | "
                       + " | ".join(f"{skill(C[m], c):+.3f} | {tests[m, grp][1]:+.1f}" for m in others) + " |")
        for m in others:
            better = [g for g in mb.GROUPS if tests[m, g][1] < -2]
            worse = [g for g in mb.GROUPS if tests[m, g][1] > 2]
            top = max(mb.GROUPS, key=lambda g: abs(tests[m, g][1]))
            out += ["", f"Against `{m}`, `global_tcn` is significantly better (t < −2) in "
                    f"{', '.join(better) or 'no group'} and significantly worse (t > +2) in {', '.join(worse) or 'no group'}; "
                    f"the largest difference is {top} ({tests[m, top][0]:+.3f}, t {tests[m, top][1]:+.1f})."]

    out += ["", "## Did the networks train?", "",
            "Epoch with the lowest validation NLL (last quarter of the training months) per seed; the final "
            "network is refitted on all training months for that many epochs. The macro_nn.py networks stopped "
            "at a median of epoch 1-2.", "",
            "| Fold | Training rows | " + " | ".join(f"{m}: best epochs" for m in variants) + " |",
            "|---|---|" + "---|" * len(variants)]
    for f in folds:
        tr = {m: f["g"]["models"][m]["training"] for m in variants}
        out.append(f"| {f['g']['fold']} | {tr[variants[0]][0]['rows']} | "
                   + " | ".join(", ".join(str(s["best_epoch"]) for s in tr[m]) for m in variants) + " |")

    keys = ("us_cpi", "uk_cpi", "ea_cpi", "us_unemp", "us_rate", "ind_gasdesw", "ind_djfuelusgulf", "ind_pcu325311325311")
    fins = [(col, tag, fin) for col, tag in BAYES if (fin := mb.load(f"{tag}-final.json"))]
    out += ["", "## Response to +10% Brent in the next month, 12 months on", "",
            "Location-only paths with and without the shock, on top of the oil path that happened, averaged over "
            "each fold's test origins and its networks (the networks are nonlinear, so the response depends on "
            "the state). In the target's units (% of the price level; pp for rates and unemployment)."
            + "".join(f" {col}: posterior mean of the all-data fit (`runs/macro/{tag}-final.json`)." for col, tag, _ in fins), "",
            "| Series | " + " | ".join(f"{m}, last fold | {m}, mean of folds" for m in variants)
            + "".join(f" | {col} (all data)" for col, _, _ in fins) + " |",
            "|---|" + "---|---|" * len(variants) + "---|" * len(fins)]
    for key in keys:
        c = names.index(f"{key}@12")
        row = []
        for m in variants:
            r = [f["g"]["models"][m]["response_up10"][c] for f in folds]
            row += [f"{r[-1]:+.2f}", f"{np.mean(r):+.2f}"]
        row += [f"{fin['responses']['up10']['mean'][fin['keys'].index(key)][11]:+.2f}" for _, _, fin in fins]
        out.append(f"| {key} | " + " | ".join(row) + " |")
    out += forecast_section(folds, refs, stack(lambda f: f["v1"]["models"]["climatology"]["crps"]), names, groups, H)
    (NOTES / "macro-global-results.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {NOTES / 'macro-global-results.md'}")


def compare(M1: np.ndarray, M2: np.ndarray, clim: np.ndarray, c) -> dict:
    """M1 against M2 (CRPS [origins, outputs]) on the origins where both score every output in c,
    in CRPS scaled by the v1 climatology's mean CRPS on those origins: each one's skill, the mean
    difference (negative: M1 better) with its Diebold-Mariano t, and how much lower M1's CRPS is (%)."""
    ok = np.isfinite(M1[:, c]).all(1) & np.isfinite(M2[:, c]).all(1)
    sc = clim[ok][:, c].mean(0)
    a, b = M1[ok][:, c] / sc, M2[ok][:, c] / sc
    d = (a - b).mean(1)
    return {"n": int(ok.sum()), "s1": 1 - a.mean(), "s2": 1 - b.mean(), "d": d.mean(), "t": mb.nw_t(d),
            "pct": 100 * (1 - a.mean() / b.mean())}


def forecast_section(folds: list[dict], refs: list, clim: np.ndarray, names: list, groups: np.ndarray,
                     H: np.ndarray) -> list[str]:
    """The report's forecast-mode sections: skill, calibration and Diebold-Mariano tests against the
    Bayesian forecast mode, then the institutional US inflation forecasts."""
    fc = [mb.load(f"global-forecast-fold-{f['g']['fold']}.json") for f in folds]
    if not all(fc):
        miss = [f["g"]["fold"] for f, x in zip(folds, fc) if not x]
        return ["", f"**No forecast mode yet:** `runs/macro/global-forecast-fold-*.json` is missing for fold(s) {miss} "
                "(`macro_global.py forecast <fold>`)."]
    bm = mb.load("global-benchmarks.json")
    for x, f in zip(fc, folds):
        assert x["test_dates"] == f["g"]["test_dates"] and x["names"] == names, f"forecast fold {x['fold']}: origins differ"
        assert np.allclose(np.array(x["y"], float), np.array(f["g"]["y"], float), equal_nan=True), \
            f"forecast fold {x['fold']}: targets differ"
    bfold = {b["fold"]: b for b in bm["folds"]} if bm else {}
    has_bm = all(x["fold"] in bfold for x in fc)
    if has_bm:
        for x in fc:
            assert bfold[x["fold"]]["test_dates"] == x["test_dates"], f"benchmarks fold {x['fold']}: origins differ"
    fv = [m for m in VARIANTS if all(m in x["models"] for x in fc)]  # variants forecast on every fold
    assert MAIN in fv, f"runs/macro/global-forecast-fold-*.json: no {MAIN} on every fold"

    def stack(get, src=fc):
        return np.vstack([np.array(get(x), float) for x in src])

    F = {m: stack(lambda x, m=m: x["models"][m]["modes"]["forecast"]["crps"]) for m in fv}
    for col, tag in refs:
        F[col] = stack(lambda f, tag=tag: f["bayes"][tag]["modes"]["forecast"]["crps"], folds)
    W = {m: stack(lambda x, m=m: x["models"][m]["modes"]["whatif"]["crps"]) for m in fv}
    W0 = {m: stack(lambda f, m=m: f["g"]["models"][m]["crps"], folds) for m in fv}
    scale = np.nanmean(clim, 0)

    def cols(grp, h="all"):
        return np.where((groups == grp) & ((H == h) if h != "all" else True))[0]

    def skill(M, c):
        return 1 - np.nanmean(np.nanmean(M[:, c], 0) / scale[c])

    every = np.arange(len(names))
    mk = fc[0]["market"]
    jobs = sorted({x["meta"]["job"] for x in fc if x.get("meta", {}).get("job")})
    when = sorted({x["meta"]["generated"] for x in fc if "meta" in x}) or ["?"]
    out = ["", "## Forecast mode: nothing after the origin", "",
           f"_`runs/macro/global-forecast-fold-*.json`, generated {when[0]}" + (f" to {when[-1]}" if len(when) > 1 else "")
           + (f" on Iridis (Slurm job IDs {', '.join(jobs)})" if jobs else " locally") + "._", "",
           "Each forecast draw follows its own oil path from `macro_bayes.oil_paths`, as in the Bayesian forecast mode: "
           "a block bootstrap (3-month blocks) of the training months' Brent changes, demeaned, scaled to the CBOE OVX "
           "implied volatility at the origin against its training mean (realised volatility where fewer than 12 "
           "training months of OVX exist), the ratio decaying back to 1, and centred on the slope of the WTI futures "
           f"curve (EIA RCLC1-4; zero drift after 2024-04). Market data fetched {mk['fetched']}. "
           "Both variants get the same oil paths and noise draws. The networks are retrained with the what-if runs' "
           "seeds; their what-if skill over all outputs is "
           + ", ".join(f"{m} {skill(W[m], every):+.3f} (`global-fold-*.json`: {skill(W0[m], every):+.3f})" for m in fv)
           + f". **{MAIN}** is the headline variant: it was chosen on what-if skill before the forecast mode was scored.", "",
           "| Target | h | " + " | ".join(f"{m} forecast" for m in F) + f" | {MAIN} what-if |",
           "|---|---|" + "---|" * (len(F) + 1)]
    for grp in mb.GROUPS:
        for h in [*mn.HORIZONS, "all"]:
            b = "**" if h == "all" else ""
            out.append(f"| {grp} | {h} | " + " | ".join(f"{b}{skill(M, cols(grp, h)):+.3f}{b}" for M in [*F.values(), W[MAIN]]) + " |")

    y_all = stack(lambda x: x["y"])
    runs = [(m, lambda x, m=m: x["models"][m]["modes"]["forecast"], fc) for m in fv]
    runs += [(col, lambda f, tag=tag: f["bayes"][tag]["modes"]["forecast"], folds) for col, tag in refs]
    out += ["", "Share of outcomes inside the central 90% interval, forecast mode (target 90%):", "",
            "| Target | " + " | ".join(r[0] for r in runs) + " |", "|---|" + "---|" * len(runs)]
    for grp in mb.GROUPS:
        c = cols(grp)
        ok = np.isfinite(y_all[:, c])
        cells = []
        for _, get, src in runs:
            lo, hi = stack(lambda x: get(x)["q05"], src), stack(lambda x: get(x)["q95"], src)
            cells.append(f"{np.mean(((y_all[:, c] >= lo[:, c]) & (y_all[:, c] <= hi[:, c]))[ok]):.0%}")
        out.append(f"| {grp} | " + " | ".join(cells) + " |")

    pairs = [(m, col) for col, _ in refs for m in fv] \
        + [(a, b) for a, b in (("global_lin", "global"), ("global_tcn", "global_lin")) if a in fv and b in fv]
    out += ["", "Diebold–Mariano tests, forecast mode: mean difference in climatology-scaled CRPS over all horizons "
            "(negative: the first is better), Newey–West t (12 lags).", "",
            "| Comparison | " + " | ".join(mb.GROUPS) + " |", "|---|" + "---|" * len(mb.GROUPS)]
    for m1, m2 in pairs + [(m, "v1 climatology") for m in fv]:
        M2 = clim if m2 == "v1 climatology" else F[m2]
        cells = [compare(F[m1], M2, clim, cols(g)) for g in mb.GROUPS]
        out.append(f"| {m1} vs {m2} | " + " | ".join(f"{r['d']:+.3f} (t {r['t']:+.1f})" for r in cells) + " |")

    if not has_bm:
        return out + ["", "**No institutional benchmarks yet:** run `macro_global.py benchmarks`."]
    B = {k: stack(lambda x, k=k: bfold[x["fold"]]["crps"][k]) for k, _ in INSTITUTIONS}
    label = dict(INSTITUTIONS)
    ours = [MAIN] + [m for m in fv if m != MAIN] + [col for col, _ in refs[:1]]  # + the main Bayesian model
    cpi = np.array([names.index("us_cpi@12")])
    out += ["", "## Against institutional US inflation forecasts (forecast mode)", "",
            f"_`runs/macro/global-benchmarks.json`: surveys fetched {bm['fetched']}, SPF to the {bm['spf_last_survey']} "
            "survey._", "",
            "- **Cleveland Fed** (FRED `EXPINF1YR`, model-based 1-year expected inflation) and **Michigan** (FRED `MICH`, "
            "households' median expected price change over the next year): month t's value at the end of month t, "
            "converted to 100 × log, as in `macro_bayes.py benchmarks`. Both are 1-year rates; at shorter horizons "
            "they are scaled by h/12, like the random walk.",
            "- **SPF**: the Philadelphia Fed's Survey of Professional Forecasters, median (and mean) headline CPI "
            "(`median_cpi_level.xlsx`, `mean_cpi_level.xlsx`). Each quarterly survey forecasts the annualised growth "
            "of the quarterly average of seasonally adjusted CPI, for its own quarter q (CPI2) and the next four "
            "(CPI3..CPI6). A survey counts as public at the end of the month of its news release, from the Philadelphia "
            "Fed's release-dates file (`spf-release-dates.txt`): mid-February, May, August or November, except 2019Q1 "
            "(released 22 March 2019 after a government shutdown). The 12-month change is read off the survey's path: "
            "each quarter's average stands for its middle month and the log level is linear in between. At the end of "
            "the middle month of quarter q (the usual release month) the 12-month change is then the survey's growth "
            "over quarters q+1..q+4 (CPI3..CPI6 de-annualised, 100 × log(1 + rate/100) / 4 each, summed), a "
            "window centred on the 12 months we score. For an origin m months later the window moves m months along "
            "the path: m/3 of quarter q+1 drops out and quarter q+4's rate carries on for m months. Shorter horizons "
            "take the first h months of the path. **Release month** scores each survey only at the end of its release "
            "month; **latest** uses the latest public survey at every month-end, 0–2 months old (3 for February 2019).",
            "- **Real-time against revised.** The surveys were made with the data as first published; every model "
            "here is trained and scored on today's revised data, which flatters the models slightly. The target, "
            "seasonally adjusted CPI (FRED `CPIAUCSL`), is revised only through its seasonal factors.",
            "- Point forecasts get a Gaussian band with the sd of their own errors on each fold's training origins. "
            "Skill and Diebold–Mariano tests (Newey–West, 12 lags) use the origins both forecasts share, with the v1 "
            "climatology's CRPS on those origins as the scale. *CRPS lower by* = 1 − our scaled CRPS / theirs "
            "(negative: ours is higher).", "",
            "### US CPI over the next 12 months", "",
            "| Benchmark | Origins | Benchmark skill | " + " | ".join(f"{m} skill" for m in ours) + " |",
            "|---|---|---|" + "---|" * len(ours)]
    R = {(m, k): compare(F[m], B[k], clim, cpi) for m in ours for k, _ in INSTITUTIONS}
    for k, _ in INSTITUTIONS:
        r0 = R[(MAIN, k)]
        out.append(f"| {label[k]} | {r0['n']} | {r0['s2']:+.3f} | " + " | ".join(f"{R[(m, k)]['s1']:+.3f}" for m in ours) + " |")
    out += ["", "| Benchmark | " + " | ".join(f"{m} minus benchmark (t) | {m} CRPS lower by" for m in ours) + " |",
            "|---|" + "---|---|" * len(ours)]
    for k, _ in INSTITUTIONS:
        out.append(f"| {label[k]} | " + " | ".join(f"{R[(m, k)]['d']:+.3f} ({R[(m, k)]['t']:+.1f}) | {R[(m, k)]['pct']:+.0f}%"
                                                for m in ours) + " |")

    us = {h: np.array([names.index(f"us_cpi@{h}")]) for h in mn.HORIZONS}
    us["all"] = np.array([names.index(f"us_cpi@{h}") for h in mn.HORIZONS])
    full = [k for k, _ in INSTITUTIONS if k not in ("spf", "spf_mean")]  # a forecast at (nearly) every origin
    n_us = {h: compare(F[MAIN], B[full[0]], clim, c)["n"] for h, c in us.items()}
    out += ["", "### US CPI by horizon", "",
            f"Skill on the origins whose outcome is known: of {len(F[MAIN])}, {n_us[12]} at 12 months and {n_us['all']} "
            "for all horizons together (US CPI for October 2025 was never published). The release-month SPF "
            "forecasts are in the next table only.", "",
            "| h | " + " | ".join(ours) + " | " + " | ".join(label[k] for k in full) + " |",
            "|---|" + "---|" * (len(ours) + len(full))]
    for h, c in us.items():
        out.append(f"| {h} | " + " | ".join(f"{compare(F[m], B[full[0]], clim, c)['s1']:+.3f}" for m in ours) + " | "
                   + " | ".join(f"{compare(F[MAIN], B[k], clim, c)['s2']:+.3f}" for k in full) + " |")
    out += ["", f"{MAIN} minus each benchmark (t), and how much lower {MAIN}'s CRPS is:", "",
            "| h | " + " | ".join(label[k] for k, _ in INSTITUTIONS) + " |", "|---|" + "---|" * len(INSTITUTIONS)]
    for h, c in us.items():
        out.append(f"| {h} | " + " | ".join(f"{r['d']:+.3f} ({r['t']:+.1f}), {r['pct']:+.0f}%"
                                         for r in (compare(F[MAIN], B[k], clim, c) for k, _ in INSTITUTIONS)) + " |")

    out += ["", "### Inflation in all three regions (US, UK, euro area): the random walk", "",
            "| Outputs | Random walk skill | " + " | ".join(f"{m} skill | {m} minus random walk (t)" for m in ours) + " |",
            "|---|---|" + "---|---|" * len(ours)]
    for lab, c in (("all horizons", cols("inflation")), ("12 months", cols("inflation", 12))):
        rs = [compare(F[m], B["rw"], clim, c) for m in ours]
        out.append(f"| inflation, {lab} | {rs[0]['s2']:+.3f} | "
                   + " | ".join(f"{r['s1']:+.3f} | {r['d']:+.3f} ({r['t']:+.1f})" for r in rs) + " |")

    # the 2025 survey dates: what each forecaster expected for the next 12 months
    i12 = int(cpi[0])
    dates = [d for x in fc for d in x["test_dates"]]
    mu = {k: stack(lambda x, k=k: bfold[x["fold"]]["mu"][k]) for k in ("spf", "cleveland", "michigan")}
    G = {m: {q: stack(lambda x, m=m, q=q: x["models"][m]["modes"]["forecast"][q]) for q in ("mu", "q05", "q95")} for m in fv}
    rows = [i for i, d in enumerate(dates) if d >= "2024-01" and np.isfinite(mu["spf"][i, i12])]
    out += ["", "### US CPI over the next 12 months at the 2024–25 survey dates", "",
            "100 × log change (≈ %). The networks' forecast mean (90% interval).", "",
            "| Origin | Actual | " + " | ".join(fv) + " | SPF median | Cleveland Fed | Michigan |", "|---|---|" + "---|" * (len(fv) + 3)]
    for i in rows:
        yv = y_all[i, i12]
        cells = [f"{G[m]['mu'][i, i12]:+.1f} ({G[m]['q05'][i, i12]:+.1f}..{G[m]['q95'][i, i12]:+.1f})" for m in fv]
        out.append(f"| {dates[i]} | {'n/a' if not np.isfinite(yv) else f'{yv:+.1f}'} | " + " | ".join(cells)
                   + f" | {mu['spf'][i, i12]:+.1f} | {mu['cleveland'][i, i12]:+.1f} | {mu['michigan'][i, i12]:+.1f} |")
    return out


# --- entry -----------------------------------------------------------------------------------

def main() -> None:
    global QUICK
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("check", "fold", "forecast", "benchmarks", "ols", "report"))
    p.add_argument("j", nargs="?", type=int, default=0)
    p.add_argument("--variant", choices=VARIANTS,
                   help="fit only this variant; fold and forecast merge it into the fold's file")
    p.add_argument("--forecast", action="store_true", help="check: run the forecast fold (both oil modes)")
    a = p.parse_args()
    if a.cmd == "report":
        return report()
    if a.cmd == "ols":
        (RUNS / "global-ols.json").write_text(json.dumps(run_ols()))
        return print(f"wrote {RUNS / 'global-ols.json'}")
    data = mn.make_dataset(mn.V1_BLOCKS)
    variants = (a.variant,) if a.variant else VARIANTS
    fvariants = (a.variant,) if a.variant else FORECAST_VARIANTS
    if a.cmd == "check":
        QUICK = True
        if a.forecast:
            out = run_forecast_fold(data, mn.FOLDS - 1, mb.market_inputs(data), fvariants)
            print({m: {mode: float(np.nanmean(r["crps"])) for mode, r in v["modes"].items()} for m, v in out["models"].items()},
                  out["market"])
            return
        out = run_fold(data, mn.FOLDS - 1, variants)
        print({m: float(np.nanmean(v["crps"])) for m, v in out["models"].items()})
        return
    RUNS.mkdir(parents=True, exist_ok=True)
    meta = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "job": os.environ.get("SLURM_JOB_ID"),
            "torch_threads": torch.get_num_threads()}
    if a.cmd == "benchmarks":
        path = RUNS / "global-benchmarks.json"
        path.write_text(json.dumps(run_benchmarks(data) | {"meta": meta}))
        return print(f"wrote {path}")
    if a.cmd == "forecast":
        path = RUNS / f"global-forecast-fold-{a.j}.json"
        out = run_forecast_fold(data, a.j, mb.market_inputs(data), fvariants)
    else:
        path = RUNS / f"global-fold-{a.j}.json"
        out = run_fold(data, a.j, variants)
    old = mb.load(path.name) if a.variant else None  # read after the run, so other variants' merges are kept
    if old is None:
        out |= {"meta": meta}
    else:
        assert old["test_dates"] == out["test_dates"] and old["names"] == out["names"], f"{path}: origins or outputs differ"
        old["models"][a.variant] = out["models"][a.variant] | {"meta": meta}  # this variant's own run date
        out = old
    path.write_text(json.dumps(out))
    print(f"wrote {path}" + (f" ({a.variant} merged)" if old else ""))


if __name__ == "__main__":
    main()
