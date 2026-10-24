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

Training: AdamW on the Student-t NLL, early stopping on the last quarter of the training months,
then a refit on all of them for the chosen number of epochs. SEEDS networks per variant form a
deep ensemble, and each forecast draw comes from one of them. Forecasts are simulated as in
macro_bayes.py: from each series' last published month, given the oil path that happened
(what-if), and scored by sample CRPS on the same forward-chaining folds and training months.

    uv run experiments/macro_global.py check      # tiny end-to-end run on the last fold
    uv run experiments/macro_global.py fold 3     # one fold -> runs/macro/global-fold-3.json
    uv run experiments/macro_global.py report     # notes/macro-global-results.md
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
import torch
from torch import nn

import macro_bayes as mb
import macro_nn as mn

ROOT = Path(__file__).resolve().parent.parent
RUNS, NOTES = ROOT / "runs" / "macro", ROOT / "notes"
OWN = 12  # lags of the series' own monthly change
EMB = 8  # series embedding width
HIDDEN, LAYERS, DROPOUT = 64, 2, 0.1
TRAIN = {"epochs": 300, "patience": 30, "lr": 2e-3, "wd": 1e-3, "batch": 256}
VAL_SHARE = 0.25  # last share of training months held out for early stopping
SEEDS = 5
VARIANTS = ("global", "global_lin")
SHOCK = np.log(1.10)  # +10% Brent in the first month, for the oil response
# Bayesian references for the report: (column, runs/macro file stem). own: each series' own recent
# volatility sets its band (macro_bayes.py --vol own, the main Bayesian model); oil: oil volatility only.
BAYES = (("Bayes own-vol", "bayes-own"), ("Bayes oil-vol", "bayes"))
QUICK = False


# --- data ------------------------------------------------------------------------------------

def features(data: dict, st: mb.Stats) -> dict:
    """Monthly arrays in standardised units: own lags [M, K, OWN] (y[s-1..s-OWN]), oil lags
    [M, LAGS] (z[s..s-12]), volatility state [M] and targets y [M, K]."""
    z = np.nan_to_num(data["oil_m"]) / st.xs
    M = len(z)
    y = (data["dM"] - st.ym) / st.ys
    own = np.stack([np.vstack([np.full((lag, y.shape[1]), np.nan), y[:M - lag]]) for lag in range(1, OWN + 1)], -1)
    oil = np.stack([np.r_[np.zeros(lag), z[:M - lag]] for lag in range(mb.LAGS)], 1)
    return {"own": own, "oil": oil, "v": (mb.log_vol(z) - st.vm) / st.vs, "y": y}


def training_rows(f: dict, last_month: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(month, series, inputs, target) for months 13..last_month where the target and the previous
    month are known, as in macro_bayes.design. Older missing own lags read as 0 (the mean)."""
    s, k = np.meshgrid(np.arange(13, last_month + 1), np.arange(f["y"].shape[1]), indexing="ij")
    ok = np.isfinite(f["y"][s, k]) & np.isfinite(f["own"][s, k, 0])
    s, k = s[ok], k[ok]
    x = np.concatenate([np.nan_to_num(f["own"][s, k]), f["oil"][s], f["v"][s, None]], 1)
    return s, k, x, f["y"][s, k]


# --- network ---------------------------------------------------------------------------------

class Net(nn.Module):
    """Shared MLP on [inputs, series embedding] -> Student-t (location, scale, tail index)."""

    def __init__(self, n_series: int, n_in: int, floor: np.ndarray, linear: bool) -> None:
        super().__init__()
        self.emb = nn.Embedding(n_series, EMB)
        layers, d = [], n_in + EMB
        for _ in range(LAYERS):
            layers += [nn.Linear(d, HIDDEN), nn.GELU(), nn.Dropout(DROPOUT)]
            d = HIDDEN
        self.body, self.head = nn.Sequential(*layers), nn.Linear(d, 3)
        # global_lin: a per-series linear term in the location, i.e. momentum and oil lags per series
        self.lin = nn.Parameter(torch.zeros(n_series, n_in)) if linear else None
        self.register_buffer("floor", torch.as_tensor(floor, dtype=torch.float32))

    def forward(self, x, k):
        h = self.head(self.body(torch.cat([x, self.emb(k)], -1)))
        loc = h[:, 0] + ((self.lin[k] * x).sum(-1) if self.lin is not None else 0.0)
        scale = self.floor[k] + nn.functional.softplus(h[:, 1])
        return loc, scale, mb.NU_MIN + nn.functional.softplus(h[:, 2])


class OLS(nn.Module):
    """Per-series least squares on the network's inputs, Gaussian errors at the residual sd above the
    same floor: the inputs without the network, to tell their gain from the network's."""

    def __init__(self, x: np.ndarray, k: np.ndarray, y: np.ndarray, floor: np.ndarray) -> None:
        super().__init__()
        K = int(k.max()) + 1
        W, sd = np.zeros((K, x.shape[1] + 1)), np.zeros(K)
        for kk in range(K):
            A = np.column_stack([x[k == kk], np.ones((k == kk).sum())])
            W[kk], *_ = np.linalg.lstsq(A, y[k == kk], rcond=None)
            sd[kk] = max((y[k == kk] - A @ W[kk]).std(), floor[kk])
        self.W, self.sd = torch.as_tensor(W, dtype=torch.float32), torch.as_tensor(sd, dtype=torch.float32)

    def forward(self, x, k):
        return (x * self.W[k, :-1]).sum(-1) + self.W[k, -1], self.sd[k], torch.full((len(x),), 1e6)


def nll(net: Net, x, k, y):
    loc, scale, nu = net(x, k)
    return -torch.distributions.StudentT(nu, loc, scale).log_prob(y).mean()


def train(x: np.ndarray, k: np.ndarray, y: np.ndarray, months: np.ndarray, floor: np.ndarray, linear: bool,
          seed: int) -> tuple[Net, dict]:
    """Early stopping on the last VAL_SHARE of the training months, then a refit on all of them for
    the best epoch count (so the latest months, the closest to the test block, are used)."""
    cfg = TRAIN | ({"epochs": 3, "patience": 1} if QUICK else {})
    X, K, Y = (torch.as_tensor(x, dtype=torch.float32), torch.as_tensor(k, dtype=torch.long),
               torch.as_tensor(y, dtype=torch.float32))
    cut = np.quantile(np.unique(months), 1 - VAL_SHARE)
    n_series = int(k.max()) + 1

    def fit(rows: np.ndarray, epochs: int, val: np.ndarray | None = None) -> tuple[Net, float, int]:
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        net = Net(n_series, x.shape[1], floor, linear)
        opt = torch.optim.AdamW(net.parameters(), lr=cfg["lr"], weight_decay=cfg["wd"])
        best, best_ep, bad, state = np.inf, epochs, 0, None
        for ep in range(1, epochs + 1):
            net.train()
            for b in np.array_split(rng.permutation(rows), max(1, len(rows) // cfg["batch"])):
                b = torch.from_numpy(b)
                loss = nll(net, X[b], K[b], Y[b])
                opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                opt.step()
            if val is None:
                continue
            net.eval()
            with torch.no_grad():
                v = nll(net, X[val], K[val], Y[val]).item()
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


# --- forecasts -------------------------------------------------------------------------------

def simulate(nets: list, st: mb.Stats, info: dict, data: dict, t: np.ndarray, future: np.ndarray, rng,
             n: int = mb.DRAWS, noise: bool = True) -> np.ndarray:
    """Draws of every output (target-major, horizon-minor, as data['names']) at origins t (month
    indices): [n, len(t), outputs], as macro_bayes.simulate with the next month's Student-t from
    the networks. Draw i comes from nets[i % len(nets)]. noise=False follows the location only."""
    K, O, pmax, H = len(info["keys"]), len(t), int(info["pub_lag"].max()), mn.OIL_AHEAD
    z_all = np.nan_to_num(data["oil_m"]) / st.xs
    y_all = (data["dM"] - st.ym) / st.ys
    zf = np.broadcast_to(future / st.xs, (n, O, H))
    s0 = t - pmax + 1  # first simulated month: every series is published up to s0 - 1
    buf = np.stack([z_all[s0 - 1 - lag] for lag in range(mb.LAGS)], -1)[None].repeat(n, 0)  # [n, O, LAGS], newest first
    own = np.stack([np.nan_to_num(y_all[s0 - lag]) for lag in range(1, OWN + 1)], -1)[None].repeat(n, 0)  # [n, O, K, OWN]
    which = np.arange(n) % len(nets)
    cum = np.zeros((n, O, K))
    out = np.zeros((n, O, K, len(mn.HORIZONS)))
    for j in range(-pmax + 1, H + 1):  # month s = t + j
        znew = zf[:, :, j - 1] if j >= 1 else np.broadcast_to(z_all[t + j], (n, O))
        buf = np.concatenate([znew[..., None], buf[..., :-1]], -1)
        v = (np.log(np.abs(buf[..., :3]).mean(-1) + mb.VOL_FLOOR) - st.vm) / st.vs  # [n, O]
        x = np.concatenate([own, np.broadcast_to(buf[:, :, None, :], (n, O, K, mb.LAGS)),
                            np.broadcast_to(v[:, :, None, None], (n, O, K, 1))], -1)
        m = np.empty((n, O, K))
        for i, net in enumerate(nets):
            sel = which == i
            if not sel.any():
                continue
            xi = torch.as_tensor(x[sel].reshape(-1, x.shape[-1]), dtype=torch.float32)
            ki = torch.as_tensor(np.tile(np.arange(K), int(sel.sum()) * O))  # series index, fastest-varying
            with torch.no_grad():
                loc, scale, nu = (a.numpy().astype(float).reshape(-1, O, K) for a in net(xi, ki))
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


def run_fold(data: dict, j: int) -> dict:
    dates = data["dates"]
    train_idx, test, last = mb.fold_window(data, j)
    info, st = mb.series_info(data), mb.Stats(data, last)
    months, k, x, y = training_rows(features(data, st), last)
    print(f"fold {j}: train months to {last} ({len(y)} rows), test {dates[test[0]]:%Y-%m}..{dates[test[-1]]:%Y-%m}",
          flush=True)
    t, Y, oil = data["t"][test], data["Y"][test], data["OIL"][test]
    shocked = oil.copy()
    shocked[:, 0] += SHOCK
    out = {"fold": j, "test_dates": [f"{d:%Y-%m}" for d in dates[test]], "names": data["names"],
           "groups": data["groups"], "y": Y.tolist(), "train_months_to": int(last), "models": {}}
    for vi, variant in enumerate(VARIANTS):
        t0 = time.time()
        fitted = [train(x, k, y, months, info["floor"], variant == "global_lin", seed=1000 * j + 100 * vi + s)
                  for s in range(2 if QUICK else SEEDS)]
        nets = [f[0] for f in fitted]
        S = simulate(nets, st, info, data, t, oil[None], np.random.default_rng(300 + j))
        # oil response: location-only paths with and without the shock, averaged over origins and networks
        base = simulate(nets, st, info, data, t, oil[None], None, n=len(nets), noise=False)
        up = simulate(nets, st, info, data, t, shocked[None], None, n=len(nets), noise=False)
        out["models"][variant] = mb.summarise(S, Y) | {
            "training": [f[1] for f in fitted], "seconds": round(time.time() - t0, 1),
            "response_up10": (up - base).mean((0, 1)).tolist()}
        ep = [f[1]["best_epoch"] for f in fitted]
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

    def stack(get):
        return np.vstack([np.array(get(f), float) for f in folds])

    scale = np.nanmean(stack(lambda f: f["v1"]["models"]["climatology"]["crps"]), 0)
    C = {name: stack(lambda f, m=name: f["g"]["models"][m]["crps"]) for name in VARIANTS}
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
    out = [
        "# Global one-step network: results", "",
        f"_Generated by `experiments/macro_global.py report` on {datetime.now(UTC).date().isoformat()} from "
        f"{len(folds)} forward-chaining folds ({first}..{last}, {n_orig} forecast origins), the same folds, "
        "training months and data as `notes/macro-bayes-results.md` (inputs: `notes/macro-panel.md`). The data are "
        "real and revised (not real-time vintages); nothing is synthetic. Every forecast here is a **what-if**: it "
        "is given the oil path that happened."
        + "".join(f" `runs/macro/{tag}-fold-*.json` generated {w[0]} to {w[-1]}." for tag, w in when.items() if w)
        + "_", "",
        "Skill = 1 − CRPS / CRPS of the v1 climatology (training mean and spread), averaged over the outputs in "
        "the group; 0 is no better than climatology. `global` is one network shared by all 22 series; "
        "`global_lin` adds a per-series linear term (momentum and oil lags) to its location. `OLS, same inputs` "
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
    runs = [(m, lambda f, m=m: f["g"]["models"][m]) for m in VARIANTS]
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

    pairs = [(m, col) for col, _ in refs for m in VARIANTS] + [("global_lin", "global")] \
        + [(m, "OLS, same inputs") for m in VARIANTS if has_ols] \
        + [("OLS, same inputs", col) for col, _ in refs if has_ols] + [(m, "v1 nn_mean") for m in VARIANTS]
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

    out += ["", "## Did the networks train?", "",
            "Epoch with the lowest validation NLL (last quarter of the training months) per seed; the final "
            "network is refitted on all training months for that many epochs. The macro_nn.py networks stopped "
            "at a median of epoch 1-2.", "",
            "| Fold | Training rows | " + " | ".join(f"{m}: best epochs" for m in VARIANTS) + " |",
            "|---|---|" + "---|" * len(VARIANTS)]
    for f in folds:
        tr = {m: f["g"]["models"][m]["training"] for m in VARIANTS}
        out.append(f"| {f['g']['fold']} | {tr[VARIANTS[0]][0]['rows']} | "
                   + " | ".join(", ".join(str(s["best_epoch"]) for s in tr[m]) for m in VARIANTS) + " |")

    keys = ("us_cpi", "uk_cpi", "ea_cpi", "us_unemp", "us_rate", "ind_gasdesw", "ind_djfuelusgulf", "ind_pcu325311325311")
    fins = [(col, tag, fin) for col, tag in BAYES if (fin := mb.load(f"{tag}-final.json"))]
    out += ["", "## Response to +10% Brent in the next month, 12 months on", "",
            "Location-only paths with and without the shock, on top of the oil path that happened, averaged over "
            "each fold's test origins and its networks (the networks are nonlinear, so the response depends on "
            "the state). In the target's units (% of the price level; pp for rates and unemployment)."
            + "".join(f" {col}: posterior mean of the all-data fit (`runs/macro/{tag}-final.json`)." for col, tag, _ in fins), "",
            "| Series | " + " | ".join(f"{m}, last fold | {m}, mean of folds" for m in VARIANTS)
            + "".join(f" | {col} (all data)" for col, _, _ in fins) + " |",
            "|---|" + "---|---|" * len(VARIANTS) + "---|" * len(fins)]
    for key in keys:
        c = names.index(f"{key}@12")
        row = []
        for m in VARIANTS:
            r = [f["g"]["models"][m]["response_up10"][c] for f in folds]
            row += [f"{r[-1]:+.2f}", f"{np.mean(r):+.2f}"]
        row += [f"{fin['responses']['up10']['mean'][fin['keys'].index(key)][11]:+.2f}" for _, _, fin in fins]
        out.append(f"| {key} | " + " | ".join(row) + " |")
    (NOTES / "macro-global-results.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {NOTES / 'macro-global-results.md'}")


# --- entry -----------------------------------------------------------------------------------

def main() -> None:
    global QUICK
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("check", "fold", "ols", "report"))
    p.add_argument("j", nargs="?", type=int, default=0)
    a = p.parse_args()
    if a.cmd == "report":
        return report()
    if a.cmd == "ols":
        (RUNS / "global-ols.json").write_text(json.dumps(run_ols()))
        return print(f"wrote {RUNS / 'global-ols.json'}")
    data = mn.make_dataset(mn.V1_BLOCKS)
    if a.cmd == "check":
        QUICK = True
        out = run_fold(data, mn.FOLDS - 1)
        print({m: float(np.nanmean(v["crps"])) for m, v in out["models"].items()})
        return
    RUNS.mkdir(parents=True, exist_ok=True)
    meta = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "job": os.environ.get("SLURM_JOB_ID")}
    path = RUNS / f"global-fold-{a.j}.json"
    path.write_text(json.dumps(run_fold(data, a.j) | {"meta": meta}))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
