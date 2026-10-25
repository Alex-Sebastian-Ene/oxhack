# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scipy>=1.11", "xlrd>=2.0", "openpyxl>=3.1", "torch>=2.2"]
# ///
"""Deep ensemble for the knock-on chain, by region and industry.

Given the last 24 months of the macro panel (experiments/macro_data.py: oil, AIS flows, US, UK and
euro-area macro, industry costs) and a path for the Brent price over the next 12 months, forecast
how inflation, unemployment and the policy rate move in each region, and how industry costs move,
1, 3, 6 and 12 months ahead, each as a Gaussian (mean and variance).

Models, each in a "base" and a scaled-down "small" size and trained with 6 seeds (deep ensemble):
  tcn              dilated causal convolutions over the 24 months
  transformer      self-attention over the 24 months
  tcn_transformer  TCN for local patterns, then a Transformer over its outputs
  lstm             recurrent network
  nbeats           N-BEATS-style stack of residual MLP blocks on the flattened window
Combinations:
  nn_mean          equal-weight mixture of every network's deep ensemble
  stack            MLP stacker with an encoder: for each output it encodes the latest month and the
                   output's identity, weighs every model's forecast (softmax) and rescales the
                   spread; trained on held-out validation forecasts
Baselines: climatology (training mean and spread), no change, ridge on the last 6 months plus the
oil path.

Inputs are standardised with training-fold statistics only, and the networks use LayerNorm.
Forward-chaining folds over 2008 onwards keep a 12-month gap before each test block, so no
training target overlaps it. Forecasts are conditional on the oil path, as the what-if needs.

    uv run experiments/macro_nn.py check            # tiny end-to-end run
    uv run experiments/macro_nn.py fold 3           # one test fold -> runs/macro/fold-3.json
    uv run experiments/macro_nn.py final            # fit on everything, oil-shock responses
    uv run experiments/macro_nn.py report           # notes/macro-nn-results.md
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

import macro_data as md

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs" / "macro"
NOTE = ROOT / "notes" / "macro-nn-results.md"
HORIZONS = (1, 3, 6, 12)
WINDOW, RIDGE_WINDOW, OIL_AHEAD = 24, 6, 12
SEEDS, FOLDS, TEST_START = 6, 8, "2008-01-01"
ARCHS = ("tcn", "transformer", "tcn_transformer", "lstm", "nbeats")
SIZES = {"base": {"d": 64, "layers": 2}, "small": {"d": 24, "layers": 1}}
TRAIN = {"epochs": 400, "patience": 40, "lr": 2e-3, "wd": 1e-2, "batch": 32, "dropout": 0.1}
QUICK = False
ANCHOR_LAGS = {"inflation": 12, "unemployment": 12, "rate": 12, "cost": 2,  # as in oil_chain.py
               "price": 12, "output": 12, "commodity": 12}  # sector runs (sector_global.py)
ANCHOR_Z = 2.0  # a target is anchored only if its summed pass-through exceeds this many HAC errors
CALIB_PRIOR = 20.0  # validation points' worth of pull towards the series-wide variance scale
torch.set_num_threads(int(os.environ.get("SLURM_CPUS_PER_TASK", 2)))


# --- data ------------------------------------------------------------------------------------

def make_dataset(blocks=md.BLOCKS, ignore_lags: bool = False, drop=()) -> dict:
    """Arrays indexed by forecast origin t (end of month t). `drop`: input-column prefixes to remove."""
    F, L, _ = md.build_panel(blocks, ignore_lags=ignore_lags)
    F = F[[c for c in F.columns if not c.startswith(tuple(drop))]] if drop else F
    reg = {s.key: s for s in md.registry(blocks)}
    targets = [k for k, s in reg.items() if s.target and k in L]
    names, groups, cols = [], [], []
    for k in targets:
        for h in HORIZONS:
            lv = L[k].values
            y = np.full(len(lv), np.nan)
            y[:-h] = (lv[h:] - lv[:-h]) * (100.0 if reg[k].transform == "dlog" else 1.0)
            cols.append(y)
            names.append(f"{k}@{h}")
            groups.append(reg[k].target)
    Y = np.column_stack(cols)
    oil = L["brent"].diff().values  # the true monthly log change: the scenario input
    OIL = np.full((len(oil), OIL_AHEAD), np.nan)
    for j in range(OIL_AHEAD):
        OIL[:-(j + 1), j] = oil[j + 1:]
    X = F.values.astype(float)
    t = np.arange(WINDOW - 1, len(F) - OIL_AHEAD)  # full window behind, full oil path ahead
    scale = {k: 100.0 if reg[k].transform == "dlog" else 1.0 for k in targets}
    return {"dates": F.index[t], "X": X, "t": t, "Y": Y[t], "OIL": OIL[t], "names": names, "groups": groups,
            "features": list(F.columns),
            # Monthly series for the linear oil anchor (true values, not lagged).
            "oil_m": oil, "target_keys": targets,
            "dM": np.column_stack([L[k].diff().values * scale[k] for k in targets]),
            "target_lags": [reg[k].anchor_lags or ANCHOR_LAGS[reg[k].target] for k in targets]}


class Scaler:
    """Standardise with training-fold statistics only (NaN-aware)."""

    def __init__(self, data: dict, train: np.ndarray) -> None:
        rows = np.unique(np.concatenate([np.arange(data["t"][i] - WINDOW + 1, data["t"][i] + 1) for i in train]))
        self.xm = np.nanmean(data["X"][rows], 0)
        self.xs = np.nanstd(data["X"][rows], 0) + 1e-8
        self.ym = np.nanmean(data["Y"][train], 0)
        self.ys = np.nanstd(data["Y"][train], 0) + 1e-8
        self.os = np.nanstd(data["OIL"][train]) + 1e-8

    def batch(self, data: dict, idx: np.ndarray):
        Xs = np.nan_to_num((data["X"] - self.xm) / self.xs)
        win = np.stack([Xs[data["t"][i] - WINDOW + 1:data["t"][i] + 1] for i in idx])
        return (torch.tensor(win, dtype=torch.float32), torch.tensor(data["OIL"][idx] / self.os, dtype=torch.float32),
                torch.tensor((data["Y"][idx] - self.ym) / self.ys, dtype=torch.float32))


# --- networks --------------------------------------------------------------------------------

class CausalBlock(nn.Module):
    def __init__(self, d: int, dilation: int, dropout: float) -> None:
        super().__init__()
        self.pad = 2 * dilation
        self.c1, self.c2 = nn.Conv1d(d, d, 3, dilation=dilation), nn.Conv1d(d, d, 3, dilation=dilation)
        self.drop, self.norm = nn.Dropout(dropout), nn.LayerNorm(d)

    def forward(self, x):  # x: [B, d, L]; left padding keeps it causal
        h = self.drop(nn.functional.gelu(self.c1(nn.functional.pad(x, (self.pad, 0)))))
        h = self.c2(nn.functional.pad(h, (self.pad, 0)))
        return self.norm((x + h).transpose(1, 2)).transpose(1, 2)


class TCN(nn.Module):
    def __init__(self, n_in: int, d: int, layers: int, dropout: float, sequence: bool = False) -> None:
        super().__init__()
        self.inp = nn.Conv1d(n_in, d, 1)
        self.blocks = nn.Sequential(*[CausalBlock(d, 2 ** i, dropout) for i in range(2 + layers)])
        self.sequence = sequence

    def forward(self, x):  # x: [B, L, F]
        h = self.blocks(self.inp(x.transpose(1, 2))).transpose(1, 2)
        return h if self.sequence else h[:, -1]


class Attention(nn.Module):
    def __init__(self, d: int, layers: int, dropout: float) -> None:
        super().__init__()
        self.pos = nn.Parameter(torch.zeros(1, WINDOW, d))
        layer = nn.TransformerEncoderLayer(d, 4, 2 * d, dropout, batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(layer, layers)
        self.norm = nn.LayerNorm(2 * d)

    def forward(self, h):  # h: [B, L, d] -> [B, 2d] (last step and mean)
        h = self.enc(h + self.pos)
        return self.norm(torch.cat([h[:, -1], h.mean(1)], -1))


class Net(nn.Module):
    """Encoder for the 24-month window, an oil-path encoder, and a Gaussian head."""

    def __init__(self, arch: str, n_in: int, n_out: int, d: int, layers: int, dropout: float) -> None:
        super().__init__()
        # "<arch>_skip": the same network plus a linear path from the oil path straight to the mean,
        # trained without weight decay, so the pass-through cannot be diluted; the network learns the rest.
        self.skip = nn.Linear(OIL_AHEAD, n_out) if arch.endswith("_skip") else None
        arch = arch.removesuffix("_skip")
        self.arch = arch
        if arch == "tcn":
            self.enc, width = TCN(n_in, d, layers, dropout), d
        elif arch == "transformer":
            self.proj, self.enc, width = nn.Linear(n_in, d), Attention(d, layers, dropout), 2 * d
        elif arch == "tcn_transformer":
            self.tcn, self.enc, width = TCN(n_in, d, layers, dropout, sequence=True), Attention(d, layers, dropout), 2 * d
        elif arch == "lstm":
            self.enc, width = nn.LSTM(n_in, d, num_layers=layers, batch_first=True,
                                      dropout=dropout if layers > 1 else 0.0), d
        elif arch == "nbeats":
            # N-BEATS-style: each block reads what earlier blocks left unexplained (the residual of the
            # flattened window) and adds its contribution to a shared forecast vector.
            flat = WINDOW * n_in
            self.in_norm = nn.LayerNorm(flat)
            self.nb_blocks = nn.ModuleList([nn.Sequential(nn.Linear(flat, 4 * d), nn.GELU(), nn.Dropout(dropout),
                                                          nn.Linear(4 * d, 4 * d), nn.GELU())
                                            for _ in range(1 + 2 * layers)])
            self.backcast = nn.ModuleList([nn.Linear(4 * d, flat) for _ in self.nb_blocks])
            self.forecast = nn.ModuleList([nn.Linear(4 * d, d) for _ in self.nb_blocks])
            width = d
        else:
            raise ValueError(arch)
        self.oil = nn.Sequential(nn.Linear(OIL_AHEAD, d), nn.GELU(), nn.Linear(d, d))
        self.head = nn.Sequential(nn.LayerNorm(width + d), nn.Linear(width + d, 2 * d), nn.GELU(),
                                  nn.Dropout(dropout), nn.Linear(2 * d, 2 * n_out))

    def forward(self, x, oil):
        if self.arch == "nbeats":
            r, z = self.in_norm(x.flatten(1)), 0.0
            for blk, back, fore in zip(self.nb_blocks, self.backcast, self.forecast):
                h = blk(r)
                r, z = r - back(h), z + fore(h)
        elif self.arch == "tcn":
            z = self.enc(x)
        elif self.arch == "transformer":
            z = self.enc(self.proj(x))
        elif self.arch == "tcn_transformer":
            z = self.enc(self.tcn(x))
        else:
            z = self.enc(x)[0][:, -1]
        out = self.head(torch.cat([z, self.oil(oil)], -1))
        mu, logvar = out.chunk(2, -1)
        if self.skip is not None:
            mu = mu + self.skip(oil)
        return mu, logvar.clamp(-8, 6)


def nll(mu, logvar, y):
    mask = ~torch.isnan(y)
    y = torch.nan_to_num(y)
    err = 0.5 * (logvar + (y - mu) ** 2 * torch.exp(-logvar))
    return (err * mask).sum() / mask.sum().clamp(min=1)


def train_net(arch, size, seed, tr, va, n_in, n_out):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    cfg = TRAIN | ({"epochs": 3, "patience": 2} if QUICK else {})
    net = Net(arch, n_in, n_out, SIZES[size]["d"], SIZES[size]["layers"], cfg["dropout"])
    skip = list(net.skip.parameters()) if net.skip is not None else []
    rest = [p for p in net.parameters() if all(p is not s for s in skip)]
    opt = torch.optim.AdamW([{"params": rest, "weight_decay": cfg["wd"]}, {"params": skip, "weight_decay": 0.0}],
                            lr=cfg["lr"])
    best, state, bad, epochs = np.inf, None, 0, 0
    for epochs in range(1, cfg["epochs"] + 1):
        net.train()
        perm = rng.permutation(len(tr[0]))
        for b in range(0, len(perm), cfg["batch"]):
            i = perm[b:b + cfg["batch"]]
            loss = nll(*net(tr[0][i], tr[1][i]), tr[2][i])
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
        net.eval()
        with torch.no_grad():
            v = nll(*net(va[0], va[1]), va[2]).item()
        if v < best - 1e-4:
            best, state, bad = v, copy.deepcopy(net.state_dict()), 0
        else:
            bad += 1
            if bad > cfg["patience"]:
                break
    net.load_state_dict(state)
    net.eval()
    return net, best, epochs


def predict(net, b):
    with torch.no_grad():
        mu, logvar = net(b[0], b[1])
    return mu.numpy(), np.exp(logvar.numpy())


def mixture(preds):
    """Moment-matched mixture of equally weighted Gaussians."""
    mus = np.stack([p[0] for p in preds])
    var = np.stack([p[1] for p in preds])
    mu = mus.mean(0)
    return mu, (var + mus ** 2).mean(0) - mu ** 2


# --- baselines and the stacker ---------------------------------------------------------------

def ridge_fit(b, alphas=(0.1, 1, 10, 100, 1000), val=None):
    def design(bb):
        return np.column_stack([bb[0][:, -RIDGE_WINDOW:].flatten(1).numpy(), bb[1].numpy(), np.ones(len(bb[0]))])

    X, Y = design(b), b[2].numpy()
    best = None
    for a in alphas:
        W = np.zeros((X.shape[1], Y.shape[1]))
        for j in range(Y.shape[1]):
            ok = ~np.isnan(Y[:, j])
            Xo = X[ok]
            W[:, j] = np.linalg.solve(Xo.T @ Xo + a * np.eye(X.shape[1]), Xo.T @ Y[ok, j])
        Xv, Yv = (design(val), val[2].numpy()) if val is not None else (X, Y)
        err = np.nanmean((Yv - Xv @ W) ** 2)
        if best is None or err < best[0]:
            best = (err, a, W)
    resid = Y - X @ best[2]
    var = np.nanmean(resid ** 2, 0) * (1 + X.shape[1] / max(len(X), 1))  # widen for estimation error
    return lambda bb: (design(bb) @ best[2], np.broadcast_to(var, (len(bb[0]), Y.shape[1])).copy()), best[1]


class Stacker(nn.Module):
    """MLP with an encoder: weights each model's forecast per output and rescales the spread."""

    def __init__(self, n_models: int, n_out: int, n_feat: int, d: int = 16) -> None:
        super().__init__()
        self.context = nn.Sequential(nn.Linear(n_feat, d), nn.GELU(), nn.LayerNorm(d))
        self.output = nn.Embedding(n_out, d)
        self.mlp = nn.Sequential(nn.Linear(2 * n_models + 2 * d, 2 * d), nn.GELU(), nn.Linear(2 * d, n_models + 1))

    def forward(self, mus, logvars, last, out_id):  # mus, logvars: [N, M]; last: [N, F]; out_id: [N]
        h = torch.cat([mus, logvars, self.context(last), self.output(out_id)], -1)
        z = self.mlp(h)
        w = torch.softmax(z[:, :-1], -1)
        mu = (w * mus).sum(-1)
        var = (w * (torch.exp(logvars) + mus ** 2)).sum(-1) - mu ** 2
        return mu, torch.log(var.clamp(min=1e-6)) + z[:, -1].clamp(-2, 2)


def stack_items(preds: dict, b):
    names = list(preds)
    N, D = preds[names[0]][0].shape
    mus = np.stack([preds[m][0] for m in names], -1).reshape(N * D, -1)
    lv = np.log(np.stack([preds[m][1] for m in names], -1).reshape(N * D, -1) + 1e-8)
    last = np.repeat(b[0][:, -1].numpy(), D, 0)
    out_id = np.tile(np.arange(D), N)
    return [torch.tensor(a, dtype=torch.float32) for a in (mus, lv, last)] + [torch.tensor(out_id)]


def train_stacker(preds_val: dict, b_val, seed=0):
    torch.manual_seed(seed)
    items = stack_items(preds_val, b_val)
    y = b_val[2].reshape(-1)
    model = Stacker(len(preds_val), b_val[2].shape[1], b_val[0].shape[2])
    opt = torch.optim.AdamW(model.parameters(), lr=3e-3, weight_decay=1e-2)
    for _ in range(5 if QUICK else 300):
        loss = nll(*model(*items), y)
        opt.zero_grad()
        loss.backward()
        opt.step()
    model.eval()

    def apply(preds, b):
        with torch.no_grad():
            mu, logvar = model(*stack_items(preds, b))
        N, D = b[2].shape
        return mu.numpy().reshape(N, D), np.exp(logvar.numpy()).reshape(N, D)

    return apply


# --- one fit, folds, scenario ----------------------------------------------------------------

def gaussian_crps(mu, var, y):
    from scipy.stats import norm
    sd = np.sqrt(var)
    z = (y - mu) / sd
    return sd * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / np.sqrt(np.pi))


class Anchor:
    """The validated linear oil pass-through for each target series, fitted on training months only.

    For each series it is oil_chain.py's link: the monthly change of the target on the current and
    lagged monthly log change of Brent (lags 0..L), with a Newey-West error on the summed effect.
    Only links whose summed effect clears ANCHOR_Z errors are kept; the rest anchor at 0. The anchor
    of an h-month forecast from origin t is the sum over months t+1..t+h of the lagged oil terms,
    using known oil up to t and the oil path after it.
    """

    def __init__(self, data: dict, last_month: int) -> None:
        import oil_chain as oc

        oil = data["oil_m"]
        self.beta, self.info = [], []
        for k, (key, lags) in enumerate(zip(data["target_keys"], data["target_lags"])):
            lagged = np.column_stack([np.concatenate([np.full(lag, np.nan), oil[:len(oil) - lag]])
                                      for lag in range(lags + 1)])
            y = data["dM"][:, k]
            ok = np.isfinite(y) & np.isfinite(lagged).all(1)
            ok[last_month + 1:] = False
            X = np.column_stack([np.ones(ok.sum()), lagged[ok]])
            b, cov = oc.ols_hac(y[ok], X, max(lags, 6))
            total, se = b[1:].sum(), float(np.sqrt(np.ones(lags + 1) @ cov[1:, 1:] @ np.ones(lags + 1)))
            keep = abs(total) > ANCHOR_Z * se
            self.beta.append(b[1:] if keep else np.zeros(lags + 1))
            self.info.append({"target": key, "lags": lags, "months": int(ok.sum()), "total": float(total),
                              "se": se, "anchored": bool(keep)})
        self.horizons = HORIZONS

    def predict(self, data: dict, idx: np.ndarray, oil_future: np.ndarray | None = None) -> np.ndarray:
        """Anchor for every output (target-major, horizon-minor, as data['names']) at origins idx."""
        future = data["OIL"][idx] if oil_future is None else oil_future
        oil = data["oil_m"]
        out = np.zeros((len(idx), len(self.beta) * len(self.horizons)))
        Lmax = max(len(b) for b in self.beta)
        for i, (t, fut) in enumerate(zip(data["t"][idx], future)):
            first = t - Lmax + 1
            past = np.concatenate([np.zeros(max(-first, 0)), oil[max(first, 0):t + 1]])
            path = np.concatenate([np.nan_to_num(past), fut])  # path[Lmax - 1] is month t
            for k, b in enumerate(self.beta):
                lags = len(b)
                monthly = [b @ path[Lmax - 1 + j - np.arange(lags)] for j in range(1, max(self.horizons) + 1)]
                cum = np.cumsum(monthly)
                for hi, h in enumerate(self.horizons):
                    out[i, k * len(self.horizons) + hi] = cum[h - 1]
        return out


def residual_data(data: dict, anchor: Anchor) -> dict:
    """What the networks learn in anchored mode: targets minus the anchor, and no oil path."""
    return dict(data, Y=data["Y"] - anchor.predict(data, np.arange(len(data["dates"]))),
                OIL=np.zeros_like(data["OIL"]))


def calibrate(models: dict, b_val, names: list[str]) -> dict:
    """Per-output variance scale so validation z^2 averages 1, pulled towards the series' own scale."""
    y = b_val[2].numpy()
    series = np.array([n.split("@")[0] for n in names])
    scales = {}
    for name, m in models.items():
        mu, var = m(b_val)
        z2 = (y - mu) ** 2 / var
        n = np.sum(np.isfinite(z2), 0)
        own = np.nanmean(np.where(np.isfinite(z2), z2, np.nan), 0)
        prior = np.array([np.nanmean(z2[:, series == s]) for s in series])
        s2 = (n * np.nan_to_num(own, nan=1.0) + CALIB_PRIOR * prior) / (n + CALIB_PRIOR)
        scales[name] = np.clip(np.nan_to_num(s2, nan=1.0), 0.25, 25.0)
    return scales


def fit_all(data: dict, train: np.ndarray, log=print):
    """Train every model on `train` origins (last quarter held out for early stopping and the stacker)."""
    gap = max(HORIZONS)
    cut = int(len(train) * 0.75)
    inner, val = train[:cut - gap], train[cut:]
    sc = Scaler(data, inner)
    b_in, b_val = sc.batch(data, inner), sc.batch(data, val)
    n_in, n_out = b_in[0].shape[2], b_in[2].shape[1]
    models, info = {}, {}
    ridge, alpha = ridge_fit(b_in, val=b_val)
    models["ridge"] = lambda b: ridge(b)
    clim_var = np.ones(n_out)
    models["climatology"] = lambda b: (np.zeros((len(b[0]), n_out)), np.broadcast_to(clim_var, (len(b[0]), n_out)).copy())
    zero = -sc.ym / sc.ys  # "no change" in standardised units
    models["no_change"] = lambda b: (np.broadcast_to(zero, (len(b[0]), n_out)).copy(),
                                     np.broadcast_to(clim_var, (len(b[0]), n_out)).copy())
    info["ridge_alpha"] = alpha
    nets = {}
    for arch in ARCHS:
        for size in SIZES:
            started = time.time()
            fitted = [train_net(arch, size, s, b_in, b_val, n_in, n_out) for s in range(SEEDS)]
            nets[f"{arch}_{size}"] = [f[0] for f in fitted]
            info[f"{arch}_{size}"] = {"val_nll": [f[1] for f in fitted], "epochs": [f[2] for f in fitted],
                                      "seconds": time.time() - started}
            log(f"  {arch}_{size}: val NLL {np.mean([f[1] for f in fitted]):.3f}, "
                f"epochs {np.mean([f[2] for f in fitted]):.0f} ({time.time() - started:.0f}s)")

    def deep(name):
        return lambda b: mixture([predict(n, b) for n in nets[name]])

    for name in nets:
        models[name] = deep(name)
    models["nn_mean"] = lambda b: mixture([predict(n, b) for name in nets for n in nets[name]])
    stack_inputs = [m for m in models if m not in ("nn_mean",)]
    stacker = train_stacker({m: models[m](b_val) for m in stack_inputs}, b_val)
    models["stack"] = lambda b: stacker({m: models[m](b) for m in stack_inputs}, b)
    info["calibration"] = calibrate(models, b_val, data["names"])
    return models, sc, info


def fold_indices(dates, j: int) -> tuple[np.ndarray, np.ndarray]:
    """Forward-chaining fold j: test block j of the post-TEST_START origins; train on every origin whose
    12-month target ends before the block starts."""
    test = np.array_split(np.flatnonzero(dates >= TEST_START), FOLDS)[j]
    return np.arange(max(test[0] - max(HORIZONS), 0)), test


def run_fold(data: dict, j: int, anchored: bool = False) -> dict:
    """Fit on fold j's training origins and score its test block.

    anchored: the oil pass-through comes from an Anchor fitted on the training months; every model
    then learns the residual without seeing the oil path, and its forecast is anchor + residual
    ("no_change" stays a true zero-change forecast, and "anchor" is the anchor alone).
    Every model is scored with its raw variance and with the validation-recalibrated one.
    """
    dates = data["dates"]
    train, test = fold_indices(dates, j)
    print(f"fold {j}: train {dates[train[0]]:%Y-%m}..{dates[train[-1]]:%Y-%m} ({len(train)}), "
          f"test {dates[test[0]]:%Y-%m}..{dates[test[-1]]:%Y-%m} ({len(test)})"
          + (" [anchored]" if anchored else ""), flush=True)
    anchor = Anchor(data, data["t"][train[-1]] + max(HORIZONS)) if anchored else None
    work = residual_data(data, anchor) if anchored else data
    models, sc, info = fit_all(work, train)
    calib = info.pop("calibration")
    info["n_train"] = len(train)
    b = sc.batch(work, test)
    y = data["Y"][test]
    A = anchor.predict(data, test) if anchored else np.zeros_like(y)
    out = {"fold": j, "anchored": anchored, "test_dates": [f"{d:%Y-%m}" for d in dates[test]],
           "names": data["names"], "groups": data["groups"], "y": y.tolist(), "info": info,
           "anchor": anchor.info if anchored else None, "models": {}}
    entries = list(models.items()) + ([("anchor", models["no_change"])] if anchored else [])
    for name, m in entries:
        mu, var = m(b)
        s2 = calib["no_change" if name == "anchor" else name]
        mu, var = mu * sc.ys + sc.ym, var * sc.ys ** 2  # back to real units
        if anchored and name != "no_change":
            mu = mu + A
        if anchored and name == "no_change":
            mu = np.zeros_like(mu)  # a true no-change forecast, not anchor + zero residual
        score = lambda v: np.where(np.isnan(y), np.nan, gaussian_crps(mu, v, np.nan_to_num(y))).tolist()  # noqa: E731
        out["models"][name] = {"mu": mu.tolist(), "var": (var * s2).tolist(), "var_raw": var.tolist(),
                               "crps": score(var * s2), "crps_raw": score(var)}
    return out


def run_final(data: dict, shock: float = np.log(1.10), recent: int = 24, anchored: bool = False) -> dict:
    """Fit on all origins; response of every output to a +10% oil move in the first month ahead.

    anchored: the networks never see the oil path, so every model's response is the anchor's.
    """
    train = np.arange(len(data["dates"]))
    idx = train[-recent:]
    if anchored:
        anchor = Anchor(data, len(data["oil_m"]) - 1)
        fut = data["OIL"][idx].copy()
        shocked = fut.copy()
        shocked[:, 0] += shock
        d = anchor.predict(data, idx, shocked) - anchor.predict(data, idx, fut)
        resp = {"anchor": {"mean": d.mean(0).tolist(), "sd_over_origins": d.std(0).tolist()}}
        return {"names": data["names"], "groups": data["groups"], "origins": [f"{data['dates'][i]:%Y-%m}" for i in idx],
                "shock": "Brent +10% in the first month ahead, rest of the path unchanged", "anchored": True,
                "responses": resp, "anchor": anchor.info}
    models, sc, info = fit_all(data, train)
    info.pop("calibration")
    base = sc.batch(data, idx)
    shocked = (base[0], base[1].clone(), base[2])
    shocked[1][:, 0] += shock / sc.os
    resp = {}
    for name, m in models.items():
        d = (m(shocked)[0] - m(base)[0]) * sc.ys
        resp[name] = {"mean": d.mean(0).tolist(), "sd_over_origins": d.std(0).tolist()}
    return {"names": data["names"], "groups": data["groups"], "origins": [f"{data['dates'][i]:%Y-%m}" for i in idx],
            "shock": "Brent +10% in the first month ahead, rest of the path unchanged", "responses": resp, "info": info}


# Each variant changes one thing, to show which weaknesses matter most. They use a reduced model
# set (ridge, two small networks with 3 seeds, the stacker) so many variants x 8 folds stay cheap.
# v1 is the first input set (oil, AIS, regions, industry), which the main fold/final runs use too;
# v2 adds fuel flows (EIA), pipeline bypass exports (AIS) and other inflation drivers, and the
# networks with a linear oil skip path.
V1_BLOCKS = ("oil", "ais", "us", "uk", "ea", "industry")
V2_ARCHS = ("lstm", "tcn_transformer", "lstm_skip", "tcn_transformer_skip")
VARIANTS = {
    "full": {},
    "no_oil_path": {"oil_path": False},  # unconditional: the model is not told the future oil path
    "no_ais": {"blocks": tuple(b for b in V1_BLOCKS if b != "ais")},
    "no_market_signals": {"drop": ("wti", "igrea", "gpr")},
    "lookahead": {"ignore_lags": True},  # pretends data are published the moment the month ends
    "shuffled_targets": {"shuffle": True},  # leakage check: skill should vanish
    "window_12": {"window": 12},
    "v2_all": {"blocks": md.BLOCKS, "archs": V2_ARCHS},
    "v2_no_fuel": {"blocks": tuple(b for b in md.BLOCKS if b != "fuel"), "archs": V2_ARCHS},
    "v2_no_pipeline": {"blocks": tuple(b for b in md.BLOCKS if b != "pipeline"), "archs": V2_ARCHS},
    "v2_no_drivers": {"blocks": tuple(b for b in md.BLOCKS if b != "drivers"), "archs": V2_ARCHS},
    "v2_no_ais_pipeline": {"blocks": tuple(b for b in md.BLOCKS if b not in ("ais", "pipeline")), "archs": V2_ARCHS},
    # Oil stocks (macro_data's optional `stocks` block: US gasoline, distillate and total stocks): compare `v1_stocks` with `full`.
    "v1_stocks": {"blocks": V1_BLOCKS + ("stocks",)},
    "v1_fuel": {"blocks": V1_BLOCKS + ("fuel",)},  # with `v1_fuel_stocks`: what stocks add next to the fuel block
    "v1_fuel_stocks": {"blocks": V1_BLOCKS + ("fuel", "stocks")},
    # The anchored model on the reduced set: compare with `full` and `no_ais` above.
    "anchored": {"anchored": True},
    "anchored_no_ais": {"blocks": tuple(b for b in V1_BLOCKS if b != "ais"), "anchored": True},
}
ABLATION_MODELS = {"archs": ("lstm", "tcn_transformer"), "sizes": ("small",), "seeds": 3}


def variant_data(variant: str) -> dict:
    """Set the globals a variant changes and build its dataset."""
    global WINDOW, ARCHS, SIZES, SEEDS
    v = VARIANTS[variant]
    WINDOW = v.get("window", WINDOW)
    ARCHS, SEEDS = v.get("archs", ABLATION_MODELS["archs"]), ABLATION_MODELS["seeds"]
    SIZES = {k: SIZES[k] for k in ABLATION_MODELS["sizes"]}
    return make_dataset(v.get("blocks", V1_BLOCKS), v.get("ignore_lags", False), v.get("drop", ()))


def run_ablation(variant: str, j: int) -> dict:
    v = VARIANTS[variant]
    data = variant_data(variant)
    if not v.get("oil_path", True):
        data["OIL"] = np.zeros_like(data["OIL"])
    if v.get("shuffle"):
        train, _ = fold_indices(data["dates"], j)
        data["Y"] = data["Y"].copy()
        data["Y"][train] = data["Y"][np.random.default_rng(j).permutation(train)]
    out = run_fold(data, j, anchored=v.get("anchored", False))
    out["variant"] = variant
    return out


def save(obj: dict, stem: str) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    obj["meta"] = {"finished": datetime.now(UTC).isoformat(), "slurm_job": os.environ.get("SLURM_ARRAY_JOB_ID")
                   or os.environ.get("SLURM_JOB_ID"), "quick": QUICK, "torch": torch.__version__}
    (RUNS / f"{stem}.json").write_text(json.dumps(obj, default=float), encoding="utf-8")
    print(f"wrote {RUNS / f'{stem}.json'}")


# --- report ----------------------------------------------------------------------------------

def hac_se(d: np.ndarray, lag: int) -> float:
    d = d - d.mean()
    n = len(d)
    v = d @ d / n
    for k in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - k / (lag + 1)) * (d[k:] @ d[:-k]) / n
    return float(np.sqrt(v / n))


CRISES = (("2008-09-01", "2009-06-01"), ("2020-03-01", "2020-12-01"), ("2022-02-01", "2022-12-01"),
          ("2026-02-01", "2026-10-01"))


def ablation_section() -> list[str]:
    files = sorted(RUNS.glob("ablate-*.json"))
    if not files:
        return []
    runs: dict[str, list] = {}
    for p in files:
        j = json.loads(p.read_text(encoding="utf-8"))
        runs.setdefault(j["variant"], []).append(j)
    groups = np.array(next(iter(runs.values()))[0]["groups"])
    shown = ("ridge", "lstm_small", "tcn_transformer_small", "lstm_skip_small", "tcn_transformer_skip_small",
             "nn_mean", "stack")
    out = ["", "## Diagnostics: what changes when one thing is removed", "",
           f"Reduced model set ({', '.join(ABLATION_MODELS['archs'])}, {ABLATION_MODELS['seeds']} seeds, small size), "
           "skill over all horizons against the climatology of the unanchored `full` variant (same test origins for "
           "every variant, so one yardstick); folds per variant in brackets. `full` is the reference.", ""]
    ref = {r["fold"]: np.array(r["models"]["climatology"]["crps"], dtype=float) for r in runs.get("full", [])}
    for g in ("inflation", "unemployment", "rate", "cost"):
        cols = groups == g
        out += [f"**{g.capitalize()}**", "", "| Variant | " + " | ".join(shown) + " |", "|---|" + "---|" * len(shown)]
        for variant in VARIANTS:
            if variant not in runs:
                continue
            rs = runs[variant]
            own = [np.array(r["models"]["climatology"]["crps"], dtype=float) for r in rs]
            clim = np.concatenate([ref.get(r["fold"], o) if ref.get(r["fold"], o).shape == o.shape else o
                                   for r, o in zip(rs, own)])
            cells = []
            for m in shown:
                if m not in rs[0]["models"]:
                    cells.append("-")
                    continue
                c = np.concatenate([np.array(r["models"][m]["crps"], dtype=float) for r in rs])
                cells.append(f"{1 - np.nanmean(c[:, cols]) / np.nanmean(clim[:, cols]):+.3f}")
            out.append(f"| {variant} ({len(rs)}) | " + " | ".join(cells) + " |")
        out.append("")
    return out


def anchored_section(v1_folds: list[dict]) -> list[str]:
    """Anchored model against v1 on the same test origins, scored against v1's climatology."""
    files = sorted(RUNS.glob("fold-anchored-*.json"))
    if not files:
        return []
    folds = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    groups, names = np.array(folds[0]["groups"]), folds[0]["names"]
    shared = {f["fold"] for f in folds} & {f["fold"] for f in v1_folds}
    v1 = [f for f in v1_folds if f["fold"] in shared]
    an = sorted([f for f in folds if f["fold"] in shared], key=lambda f: f["fold"])
    v1 = sorted(v1, key=lambda f: f["fold"])

    def stack(fs, m, key):
        return np.concatenate([np.array(f["models"][m][key], dtype=float) for f in fs])

    clim = stack(v1, "climatology", "crps")
    shock = np.log(1.10)
    out = ["", "## Anchored model: the oil pass-through fixed to the validated linear links", "",
           f"_{len(an)} folds (Iridis job {an[0]['meta'].get('slurm_job')}), same test origins as above. Each fold "
           f"fits, on its training months only, the `oil_chain.py` link for every target series (monthly change on "
           f"Brent lags 0–12 for inflation, unemployment, rates and materials, 0–2 for fuel and freight) and anchors "
           f"it only if the summed effect clears {ANCHOR_Z:g} Newey–West errors. The networks and baselines then "
           "learn the residual without seeing the oil path, and every interval is rescaled on the validation set. "
           "Skill is against the *unanchored* climatology, so both runs share one yardstick._", "",
           "**Which links are anchored** (folds where the link cleared the bar; effect of a sustained +10% Brent "
           "move on the summed monthly changes, in the target's units, mean over anchored folds):", "",
           "| Target | Lags | Folds anchored | Effect of +10% oil |", "|---|---|---|---|"]
    for k, info in enumerate(an[0]["anchor"]):
        per = [f["anchor"][k] for f in an]
        hits = [p for p in per if p["anchored"]]
        eff = f"{np.mean([p['total'] for p in hits]) * shock:+.3f}" if hits else "not anchored"
        out.append(f"| {info['target']} | 0–{info['lags']} | {len(hits)}/{len(per)} | {eff} |")
    out += ["", "**Skill vs the unanchored climatology, all horizons** (v1 = unanchored run above; raw = anchored with "
                "the networks' own variances; recalibrated = anchored with validation-rescaled variances):", "",
            "| Model | " + " | ".join(f"{g}: v1 / raw / recal." for g in ("inflation", "unemployment", "rate", "cost")) + " |",
            "|---|" + "---|" * 4]
    for m in ("anchor", "stack", "nn_mean", "ridge", "climatology", "lstm_base", "lstm_small", "tcn_transformer_base",
              "transformer_base", "no_change"):
        if m not in an[0]["models"]:
            continue
        cells = []
        for g in ("inflation", "unemployment", "rate", "cost"):
            cols = groups == g
            base = np.nanmean(clim[:, cols])
            v = f"{1 - np.nanmean(stack(v1, m, 'crps')[:, cols]) / base:+.3f}" if m in v1[0]["models"] else "-"
            raw = 1 - np.nanmean(stack(an, m, "crps_raw")[:, cols]) / base
            cal = 1 - np.nanmean(stack(an, m, "crps")[:, cols]) / base
            cells.append(f"{v} / {raw:+.3f} / **{cal:+.3f}**")
        out.append(f"| {m} | " + " | ".join(cells) + " |")
    # Hybrid: anchored (recalibrated) for the groups with validated oil links, unanchored for the rest.
    priced = np.isin(groups, ["inflation", "cost"])
    out += ["", "**Hybrid** (anchored and recalibrated for inflation and costs; unanchored, with the oil path as an "
                "input, for unemployment and rates):", "",
            "| Model | inflation | unemployment | rate | cost |", "|---|---|---|---|---|"]
    for m in ("nn_mean", "stack", "lstm_base", "ridge", "climatology"):
        if m not in an[0]["models"] or m not in v1[0]["models"]:
            continue
        hyb = np.where(priced, stack(an, m, "crps"), stack(v1, m, "crps"))
        out.append(f"| {m} | " + " | ".join(f"{1 - np.nanmean(hyb[:, groups == g]) / np.nanmean(clim[:, groups == g]):+.3f}"
                                             for g in ("inflation", "unemployment", "rate", "cost")) + " |")
    from scipy.stats import norm
    y = np.concatenate([np.array(f["y"], dtype=float) for f in an])
    out += ["", "**Calibration: share inside the central 90% interval** (target 90%), anchored raw → recalibrated:", "",
            "| Model | inflation | unemployment | rate | cost |", "|---|---|---|---|---|"]
    for m in ("anchor", "stack", "nn_mean", "ridge", "lstm_base", "tcn_transformer_base"):
        if m not in an[0]["models"]:
            continue
        mu = stack(an, m, "mu")
        cells = []
        for g in ("inflation", "unemployment", "rate", "cost"):
            cols = groups == g
            got = []
            for key in ("var_raw", "var"):
                inside = np.abs(y - mu) <= norm.ppf(0.95) * np.sqrt(stack(an, m, key))
                got.append(np.nanmean(np.where(np.isnan(y[:, cols]), np.nan, inside[:, cols])))
            cells.append(f"{got[0]:.0%} → **{got[1]:.0%}**")
        out.append(f"| {m} | " + " | ".join(cells) + " |")
    final = RUNS / "final-anchored.json"
    if final.exists():
        fin = json.loads(final.read_text(encoding="utf-8"))
        r = fin["responses"]["anchor"]["mean"]
        v1fin = json.loads((RUNS / "final.json").read_text(encoding="utf-8")) if (RUNS / "final.json").exists() else None
        out += ["", "**Response to a +10% Brent move in the next month, 12 months ahead** (anchored = every model, "
                    "fitted on all data; v1 = the unanchored ensemble mean and stacker):", "",
                "| Output | anchored | v1 nn_mean | v1 stack | anchored in final fit |", "|---|---|---|---|---|"]
        anchored_keys = {i["target"]: i["anchored"] for i in fin["anchor"]}
        for i, n in enumerate(fin["names"]):
            if n.endswith("@12"):
                v1r = (f"{v1fin['responses']['nn_mean']['mean'][i]:+.3f} | {v1fin['responses']['stack']['mean'][i]:+.3f}"
                       if v1fin else "- | -")
                out.append(f"| {n[:-3]} | **{r[i]:+.3f}** | {v1r} | {'yes' if anchored_keys[n[:-3]] else 'no'} |")
        out.append("")
        out.append("Linear link for comparison (`notes/oil-chain-links.md`, US, 1991–2008 fit): headline CPI +0.36 pp.")
    return out


def write_report() -> None:
    folds = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RUNS.glob("fold-[0-9]*.json"))]
    names, groups = folds[0]["names"], np.array(folds[0]["groups"])
    models = list(folds[0]["models"])
    crps = {m: np.concatenate([np.array(f["models"][m]["crps"], dtype=float) for f in folds]) for m in models}
    y = np.concatenate([np.array(f["y"], dtype=float) for f in folds])
    dates = sum((f["test_dates"] for f in folds), [])
    horizons = np.array([int(n.split("@")[1]) for n in names])
    clim = crps["climatology"]
    quick = any(f["meta"].get("quick") for f in folds)
    out = [
        "# Deep ensemble for the knock-on chain: results",
        "",
        f"_Generated by `experiments/macro_nn.py report` on {datetime.now(UTC).date().isoformat()} from {len(folds)} "
        f"forward-chaining folds (test {dates[0]}..{dates[-1]}, {len(dates)} forecast origins; Iridis job "
        f"{folds[0]['meta'].get('slurm_job')}). Inputs and targets: `notes/macro-panel.md`. "
        + ("**SMOKE TEST (--quick): numbers are not results.** " if quick else "")
        + "Nothing here is synthetic._",
        "",
        "Skill = 1 − CRPS / CRPS of climatology (training mean and spread), averaged over outputs in the group; "
        "higher is better, 0 means no better than climatology. Forecasts are conditional on the realised oil path.",
        "",
    ]
    for g in ("inflation", "unemployment", "rate", "cost"):
        cols = groups == g
        if not cols.any():
            continue
        out += [f"## {g.capitalize()} ({cols.sum() // len(HORIZONS)} series)", "",
                "| Model | " + " | ".join(f"h={h}" for h in HORIZONS) + " | all h | vs ridge (CRPS diff, ± HAC) |",
                "|---|" + "---|" * (len(HORIZONS) + 2)]
        rows = []
        for m in models:
            cells = []
            for h in HORIZONS:
                c = cols & (horizons == h)
                cells.append(1 - np.nanmean(crps[m][:, c]) / np.nanmean(clim[:, c]))
            allh = 1 - np.nanmean(crps[m][:, cols]) / np.nanmean(clim[:, cols])
            rel = np.nanmean(crps[m][:, cols] / np.nanmean(clim[:, cols], 0), 1) \
                - np.nanmean(crps["ridge"][:, cols] / np.nanmean(clim[:, cols], 0), 1)
            rel = rel[~np.isnan(rel)]
            rows.append((allh, f"| {m} | " + " | ".join(f"{c:+.3f}" for c in cells) + f" | **{allh:+.3f}** | "
                         f"{rel.mean():+.4f} ± {hac_se(rel, 12):.4f} |"))
        out += [r for _, r in sorted(rows, key=lambda r: -r[0])] + [""]
    out += ["## Calibration: share of outcomes inside the central 90% interval (target 90%)", "",
            "| Model | inflation | unemployment | rate | cost |", "|---|---|---|---|---|"]
    from scipy.stats import norm
    for m in models:
        mu = np.concatenate([np.array(f["models"][m]["mu"], dtype=float) for f in folds])
        var = np.concatenate([np.array(f["models"][m]["var"], dtype=float) for f in folds])
        inside = np.abs(y - mu) <= norm.ppf(0.95) * np.sqrt(var)
        cells = [f"{np.nanmean(np.where(np.isnan(y[:, groups == g]), np.nan, inside[:, groups == g])):.0%}"
                 if (groups == g).any() else "-" for g in ("inflation", "unemployment", "rate", "cost")]
        out.append(f"| {m} | " + " | ".join(cells) + " |")
    # Learning curve: the folds are expanding windows, so skill by fold shows what more data buys.
    out += ["", "## By fold: does more training data help?", "",
            "| Fold | Test origins | Training origins | stack | nn_mean | ridge | best single network | its skill |",
            "|---|---|---|---|---|---|---|---|"]
    nets = [m for m in models if m.rsplit("_", 1)[-1] in SIZES]
    for f in folds:
        c = {m: np.array(f["models"][m]["crps"], dtype=float) for m in models}
        sk = {m: 1 - np.nanmean(c[m] / np.nanmean(c["climatology"], 0)) for m in models}
        best = max(nets, key=sk.get)
        first_origin = pd.Timestamp(md.START) + pd.DateOffset(months=WINDOW - 1)
        months_before = (pd.Timestamp(f["test_dates"][0]).year - first_origin.year) * 12 \
            + pd.Timestamp(f["test_dates"][0]).month - first_origin.month
        n_train = f["info"].get("n_train", months_before - max(HORIZONS))
        out.append(f"| {f['fold']} | {f['test_dates'][0]}..{f['test_dates'][-1]} | {n_train} | {sk['stack']:+.3f} | "
                   f"{sk['nn_mean']:+.3f} | {sk['ridge']:+.3f} | {best} | {sk[best]:+.3f} |")
    out.append("")
    out.append("Skill here is averaged over all 88 outputs, each scaled by its own climatology CRPS.")

    # Crisis vs calm: an origin counts as "crisis" if any month it forecasts falls in a crisis window.
    crisis_months = pd.DatetimeIndex([])
    for lo, hi in CRISES:
        crisis_months = crisis_months.union(pd.date_range(lo, hi, freq="MS"))
    origin = pd.to_datetime(dates)
    in_crisis = np.array([any((d + pd.DateOffset(months=k)) in crisis_months for k in range(1, max(HORIZONS) + 1))
                          for d in origin])
    out += ["", "## Crisis vs calm forecast origins", "",
            "Crisis windows: " + ", ".join(f"{lo[:7]} to {hi[:7]}" for lo, hi in CRISES)
            + f". {in_crisis.sum()} of {len(origin)} origins forecast into one. Skill vs climatology, all horizons.", "",
            "| Model | " + " | ".join(f"{g} calm | {g} crisis" for g in ("inflation", "unemployment", "rate", "cost"))
            + " |", "|---|" + "---|---|" * 4]
    for m in ("stack", "nn_mean", "ridge", "tcn_transformer_base", "lstm_base", "no_change"):
        if m not in crps:
            continue
        cells = []
        for g in ("inflation", "unemployment", "rate", "cost"):
            cols = groups == g
            for rows in (~in_crisis, in_crisis):
                cells.append(f"{1 - np.nanmean(crps[m][rows][:, cols]) / np.nanmean(clim[rows][:, cols]):+.3f}")
        out.append(f"| {m} | " + " | ".join(cells) + " |")
    out += anchored_section(folds)
    out += ablation_section()
    final = RUNS / "final.json"
    if final.exists():
        fin = json.loads(final.read_text(encoding="utf-8"))
        out += ["", f"## Response to a +10% Brent move (fit on all data; mean over origins {fin['origins'][0]}.."
                    f"{fin['origins'][-1]})", "",
                "12 months ahead, in the target's units (pp for inflation and costs = % of the price level; pp for "
                "rates and unemployment). Linear link from `notes/oil-chain-links.md` for comparison: US CPI +0.36 pp.",
                "", "| Output | stack | nn_mean | ridge | tcn_transformer_base | transformer_base |",
                "|---|---|---|---|---|---|"]
        for i, n in enumerate(fin["names"]):
            if n.endswith("@12"):
                r = fin["responses"]
                out.append(f"| {n[:-3]} | " + " | ".join(f"{r[m]['mean'][i]:+.3f}" for m in
                                                          ("stack", "nn_mean", "ridge", "tcn_transformer_base",
                                                           "transformer_base")) + " |")
    v2 = RUNS / "final-v2_all.json"
    if v2.exists():
        fin2 = json.loads(v2.read_text(encoding="utf-8"))
        r = fin2["responses"]
        cols = [m for m in ("lstm_skip_small", "tcn_transformer_skip_small", "lstm_small", "tcn_transformer_small",
                            "nn_mean", "ridge") if m in r]
        out += ["", "## Response to a +10% Brent move with the v2 inputs and the oil skip path", "",
                "Same shock and units as above; v2 inputs (fuel flows, pipeline bypass exports, other drivers); "
                "`_skip` networks have a linear oil-path term added to the mean.", "",
                "| Output | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
        for i, n in enumerate(fin2["names"]):
            if n.endswith("@12"):
                out.append(f"| {n[:-3]} | " + " | ".join(f"{r[m]['mean'][i]:+.3f}" for m in cols) + " |")
    out.append("")
    NOTE.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {NOTE}")


def main() -> None:
    global QUICK, SEEDS
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    f = sub.add_parser("fold")
    f.add_argument("j", type=int)
    a = sub.add_parser("ablate", help="one diagnostic variant on one fold (see VARIANTS)")
    a.add_argument("variant", choices=list(VARIANTS))
    a.add_argument("j", type=int)
    fi = sub.add_parser("final")
    fi.add_argument("--variant", choices=list(VARIANTS), help="fit a diagnostic variant instead of the main set")
    sub.add_parser("report")
    for q in (f, a, fi):
        q.add_argument("--quick", action="store_true")
    for q in (f, fi, sub.choices["check"]):
        q.add_argument("--anchored", action="store_true", help="oil pass-through from the linear anchor")
    args = p.parse_args()
    if args.cmd == "report":
        write_report()
        return
    QUICK = getattr(args, "quick", False) or args.cmd == "check"
    if args.cmd == "ablate":
        save(run_ablation(args.variant, args.j), f"ablate-{args.variant}-fold-{args.j}")
        return
    if args.cmd == "final" and args.variant:
        v = VARIANTS[args.variant]
        save(run_final(variant_data(args.variant), anchored=v.get("anchored", False)), f"final-{args.variant}")
        return
    if args.cmd == "check":
        SEEDS = 2
    data = make_dataset(V1_BLOCKS)
    print(f"dataset: {len(data['dates'])} origins {data['dates'][0]:%Y-%m}..{data['dates'][-1]:%Y-%m}, "
          f"{len(data['features'])} inputs, {len(data['names'])} outputs", flush=True)
    tag = "anchored-" if args.anchored else ""
    if args.cmd in ("fold", "check"):
        j = getattr(args, "j", FOLDS - 1)
        save(run_fold(data, j, anchored=args.anchored),
             f"fold-{tag}{j}" if args.cmd == "fold" else ("check-anchored" if args.anchored else "check"))
    else:
        save(run_final(data, anchored=args.anchored), f"final{'-anchored' if args.anchored else ''}")


if __name__ == "__main__":
    main()
