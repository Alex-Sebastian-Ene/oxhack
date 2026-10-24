# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scipy>=1.11", "xlrd>=2.0", "openpyxl>=3.1", "torch>=2.2",
#                 "jax>=0.4.30", "numpyro>=0.15"]
# ///
"""Bayesian oil pass-through for the knock-on chain, fitted by MCMC (NUTS).

One model for all 22 target series of experiments/macro_nn.py (inflation, unemployment and the
policy rate in three regions, 13 industry costs), on their monthly changes, fitted on each fold's
training months only:

    y[s,k] = a[k] + rho[k] y[s-1,k] + sum_l B[k,l] (x+[s-l] (1 + alpha[k]) + x-[s-l] (1 - alpha[k])) + e[s,k]
    e[s,k] ~ Student-t(nu[k], 0, sigma[k] exp(phi[k] v[s]))

- x: monthly log change of Brent (standardised); x+ and x- are its rises and falls. alpha > 0
  means rises pass through faster than falls ("rockets and feathers").
- B: lag coefficients (0..12 months, or 0..2 for fuel and freight, as in the anchor), pooled
  towards a mean per target group and lag length: short series borrow strength from their group.
- rho: momentum in the series' own monthly change, which is what a short-horizon forecast uses.
- v: recent oil volatility (log mean |x| over 3 months, standardised), so the band widens in oil
  turmoil instead of everywhere.

Forecasts are simulated month by month from each series' last published month, over posterior
draws, so they carry parameter uncertainty, fat tails and the volatility state. Two oil modes are
scored on the same forward-chaining folds as macro_nn.py:
    whatif    the oil path that happened (the what-if, as in macro_nn.py)
    forecast  oil paths simulated by block bootstrap of training months, scaled to the recent
              volatility (a genuine forecast: nothing after the origin is known)

    uv run experiments/macro_bayes.py check        # tiny end-to-end run
    uv run experiments/macro_bayes.py fold 3       # one test fold -> runs/macro/bayes-fold-3.json
    uv run experiments/macro_bayes.py final        # all data: posterior oil-shock responses
    uv run experiments/macro_bayes.py report       # notes/macro-bayes-results.md
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

CHAINS = int(os.environ.get("BAYES_CHAINS", 2))
os.environ.setdefault("XLA_FLAGS", f"--xla_force_host_platform_device_count={CHAINS}")

import jax  # noqa: E402
import jax.numpy as jnp  # noqa: E402
import numpy as np  # noqa: E402
import numpyro  # noqa: E402
import numpyro.distributions as dist  # noqa: E402
import pandas as pd  # noqa: E402
from numpyro.infer import MCMC, NUTS  # noqa: E402

import macro_data as md  # noqa: E402
import macro_nn as mn  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RUNS, NOTES = ROOT / "runs" / "macro", ROOT / "notes"
LAGS = 13  # oil lags 0..12
WARMUP = int(os.environ.get("BAYES_WARMUP", 500))  # per chain
SAMPLES, DRAWS = 500, 400  # per chain; DRAWS posterior draws are used for forecasts
TREE_DEPTH = 8
BLOCK = 3  # months per bootstrap block of oil changes
VOL_FLOOR = 0.05  # added to mean |x| before the log, so calm months don't run to -inf
NU_MIN = 2.5  # Student-t tail floor
# Error-scale floor, in each series' training sd. Policy rates move in discrete steps and sit still for
# years (the ECB deposit rate was flat 2016-2022), so a continuous model needs a wider floor there, or
# drift and momentum trade off in two separate modes (fold 6 had R-hat 17 on ea_rate at 0.05).
SIGMA_FLOOR = {"rate": 0.2}
SIGMA_FLOOR_DEFAULT = 0.05
QUICK = False


# --- data ------------------------------------------------------------------------------------

def series_info(data: dict) -> dict:
    """Per target series: group, publication lag, oil lags, and the pooling cluster (group x lags)."""
    reg = {s.key: s for s in md.registry(md.BLOCKS)}
    keys = data["target_keys"]
    groups = [reg[k].target for k in keys]
    clusters = sorted(set(zip(groups, data["target_lags"])))
    return {"keys": keys, "groups": groups, "pub_lag": np.array([reg[k].lag for k in keys]),
            "lags": np.array(data["target_lags"]),
            "cluster": np.array([clusters.index(c) for c in zip(groups, data["target_lags"])]),
            "clusters": [f"{g}/{n}" for g, n in clusters]}


class Stats:
    """Standardisation of oil, volatility state and targets from training months only."""

    def __init__(self, data: dict, last_month: int) -> None:
        x = data["oil_m"][1:last_month + 1]
        self.xm, self.xs = 0.0, float(np.nanstd(x))
        self.x2 = float(np.nanmean(x ** 2))
        lv = log_vol(np.nan_to_num(data["oil_m"]) / self.xs)[13:last_month + 1]
        self.vm, self.vs = float(lv.mean()), float(lv.std())
        y = data["dM"][13:last_month + 1]
        self.ym, self.ys = np.nanmean(y, 0), np.nanstd(y, 0)


def log_vol(z: np.ndarray) -> np.ndarray:
    a = np.abs(z)
    return np.log((a + np.r_[0, a[:-1]] + np.r_[0, 0, a[:-2]]) / 3 + VOL_FLOOR)


def design(data: dict, st: Stats, last_month: int) -> dict:
    """Training arrays: lagged rises/falls [S, LAGS], volatility state [S], y and y[s-1] [S, K]."""
    z = np.nan_to_num(data["oil_m"]) / st.xs
    lag = np.stack([np.concatenate([np.zeros(l), z[:len(z) - l]]) for l in range(LAGS)], 1)
    v = (log_vol(z) - st.vm) / st.vs
    y = (data["dM"] - st.ym) / st.ys
    rows = np.arange(13, last_month + 1)  # full oil lags behind every training month
    return {"Xp": np.maximum(lag, 0)[rows], "Xn": np.minimum(lag, 0)[rows], "v": v[rows],
            "y": y[rows], "yprev": y[rows - 1]}


# --- model -----------------------------------------------------------------------------------

def model(Xp, Xn, v, yprev, y, lagmask, cluster, n_clusters, floor):
    K = y.shape[1]
    mu = numpyro.sample("mu", dist.Normal(0, 0.5).expand([n_clusters, LAGS]).to_event(2))
    tau = numpyro.sample("tau", dist.HalfNormal(0.2).expand([n_clusters, 1]).to_event(2))
    bz = numpyro.sample("bz", dist.Normal(0, 1).expand([K, LAGS]).to_event(2))
    B = numpyro.deterministic("B", (mu[cluster] + tau[cluster] * bz) * lagmask)  # non-centred pooling
    a = numpyro.sample("a", dist.Normal(0, 1).expand([K]).to_event(1))
    rho = numpyro.deterministic("rho", 0.95 * jnp.tanh(numpyro.sample("rho_raw", dist.Normal(0, 0.5).expand([K]).to_event(1))))
    alpha = numpyro.deterministic("alpha", 0.9 * jnp.tanh(numpyro.sample("alpha_raw", dist.Normal(0, 0.5).expand([K]).to_event(1))))
    # The floor keeps a series that sits still for years (policy rates at zero: most monthly changes
    # are exactly 0) from collapsing its scale towards 0, which strands chains in that spike.
    sigma = numpyro.deterministic("sigma", floor + numpyro.sample("sigma_raw", dist.HalfNormal(1).expand([K]).to_event(1)))
    phi = numpyro.sample("phi", dist.Normal(0, 0.5).expand([K]).to_event(1))
    nu = numpyro.deterministic("nu", NU_MIN + numpyro.sample("nu_m", dist.Gamma(2, 0.1).expand([K]).to_event(1)))
    ok = jnp.isfinite(y) & jnp.isfinite(yprev)
    m = a + rho * jnp.nan_to_num(yprev) + (Xp @ B.T) * (1 + alpha) + (Xn @ B.T) * (1 - alpha)
    scale = sigma * jnp.exp(phi * v[:, None])
    with numpyro.handlers.mask(mask=ok):
        numpyro.sample("y", dist.StudentT(nu, m, scale), obs=jnp.nan_to_num(y))


KEEP = ("B", "a", "rho", "alpha", "sigma", "phi", "nu")


def fit(data: dict, last_month: int, seed: int = 0) -> tuple[dict, Stats, dict, dict]:
    """NUTS on months 13..last_month. Returns posterior draws (KEEP), stats, series info, diagnostics."""
    info = series_info(data)
    st = Stats(data, last_month)
    d = design(data, st, last_month)
    lagmask = (np.arange(LAGS)[None, :] <= info["lags"][:, None]).astype(float)
    warm, samp = (40, 40) if QUICK else (WARMUP, SAMPLES)
    mcmc = MCMC(NUTS(model, target_accept_prob=0.9, max_tree_depth=TREE_DEPTH), num_warmup=warm,
                num_samples=samp, num_chains=CHAINS, chain_method="parallel", progress_bar=False)
    t0 = time.time()
    mcmc.run(jax.random.PRNGKey(seed), extra_fields=("diverging", "num_steps"),
             **{k: jnp.asarray(v) for k, v in d.items()}, lagmask=jnp.asarray(lagmask),
             cluster=jnp.asarray(info["cluster"]), n_clusters=len(info["clusters"]),
             floor=jnp.asarray([SIGMA_FLOOR.get(g, SIGMA_FLOOR_DEFAULT) for g in info["groups"]]))
    grouped = mcmc.get_samples(group_by_chain=True)
    summ = numpyro.diagnostics.summary({k: np.asarray(grouped[k]) for k in ("bz", "a", "rho_raw", "alpha_raw", "sigma_raw", "phi")})
    rhat = max(float(np.nanmax(s["r_hat"])) for s in summ.values())
    ess = min(float(np.nanmin(s["n_eff"])) for s in summ.values())
    extra = mcmc.get_extra_fields()
    diag = {"seconds": round(time.time() - t0, 1), "chains": CHAINS, "warmup": warm, "samples": samp,
            "divergences": int(np.sum(extra["diverging"])), "max_r_hat": round(rhat, 3), "min_ess": round(ess, 1),
            "tree_depth_hits": int(np.sum(np.asarray(extra["num_steps"]) >= 2 ** TREE_DEPTH - 1)),
            "months": int(np.isfinite(d["y"]).any(1).sum())}
    post = {k: np.asarray(v) for k, v in mcmc.get_samples().items() if k in KEEP}
    n = len(post["a"])
    pick = np.random.default_rng(seed).choice(n, size=min(DRAWS if not QUICK else 50, n), replace=False)
    return {k: v[pick] for k, v in post.items()}, st, info, diag


# --- forecasts -------------------------------------------------------------------------------

def oil_paths(data: dict, st: Stats, last_month: int, t: np.ndarray, n: int, rng) -> np.ndarray:
    """Simulated monthly Brent log changes after each origin [n, len(t), 12]: block bootstrap of the
    training months, demeaned, scaled by recent volatility relative to the training average (the
    ratio decays back to 1 over the path)."""
    x = data["oil_m"][1:last_month + 1]
    x = x[np.isfinite(x)] - np.nanmean(x)
    starts = rng.integers(0, len(x) - BLOCK, size=(n, len(t), -(-mn.OIL_AHEAD // BLOCK)))
    path = np.concatenate([x[starts + b][..., None] for b in range(BLOCK)], -1).reshape(n, len(t), -1)[..., :mn.OIL_AHEAD]
    recent = np.array([np.nanmean(data["oil_m"][max(i - 2, 1):i + 1] ** 2) for i in t])
    ratio = np.clip(np.sqrt(recent / st.x2), 0.5, 3.0)
    decay = 0.8 ** np.arange(1, mn.OIL_AHEAD + 1)
    return path * (1 + (ratio[:, None] - 1) * decay[None, :])[None]


def simulate(post: dict, st: Stats, info: dict, data: dict, t: np.ndarray, future: np.ndarray, rng,
             noise: bool = True) -> np.ndarray:
    """Draws of every output (target-major, horizon-minor, as data['names']) at origins t (month
    indices): [N, len(t), outputs]. future: oil log changes after each origin, [N or 1, len(t), 12].

    Each series is simulated from its last published month (t - publication lag), so months that
    have happened but are not yet published are nowcast, as a forecaster at the end of month t would."""
    N, K = len(post["a"]), len(info["keys"])
    O, pmax, H = len(t), int(info["pub_lag"].max()), mn.OIL_AHEAD
    z_all = np.nan_to_num(data["oil_m"]) / st.xs
    y_all = (data["dM"] - st.ym) / st.ys
    zf = np.broadcast_to(future / st.xs, (N, O, H))
    B, a, rho, alpha = post["B"], post["a"], post["rho"], post["alpha"]
    sig, phi, nu = post["sigma"], post["phi"], post["nu"]
    # buffer of the last LAGS oil changes before the first simulated month, newest first
    s0 = t - pmax + 1
    buf = np.stack([z_all[s0 - 1 - l] for l in range(LAGS)], -1)[None].repeat(N, 0)  # [N, O, LAGS]
    yprev = np.nan_to_num(y_all[s0 - 1])[None].repeat(N, 0)  # [N, O, K]
    cum = np.zeros((N, O, K))
    out = np.zeros((N, O, K, len(mn.HORIZONS)))
    for j in range(-pmax + 1, H + 1):  # month s = t + j
        znew = zf[:, :, j - 1] if j >= 1 else np.broadcast_to(z_all[t + j], (N, O))
        buf = np.concatenate([znew[..., None], buf[..., :-1]], -1)
        v = (np.log(np.abs(buf[..., :3]).mean(-1) + VOL_FLOOR) - st.vm) / st.vs  # [N, O]
        m = (a[:, None] + rho[:, None] * yprev
             + np.einsum("nol,nkl->nok", np.maximum(buf, 0), B) * (1 + alpha[:, None])
             + np.einsum("nol,nkl->nok", np.minimum(buf, 0), B) * (1 - alpha[:, None]))
        if noise:
            m = m + rng.standard_t(nu[:, None, :], size=(N, O, K)) * sig[:, None] * np.exp(phi[:, None] * v[..., None])
        known = j <= -info["pub_lag"]  # [K]: this month is already published for these series
        if known.any():
            obs = y_all[t + j]
            m = np.where(known & np.isfinite(obs)[None], np.nan_to_num(obs)[None], m)
        yprev = m
        if j >= 1:
            cum = cum + m * st.ys + st.ym
            for hi, h in enumerate(mn.HORIZONS):
                if j == h:
                    out[..., hi] = cum
    return out.reshape(N, O, K * len(mn.HORIZONS))


def crps_samples(S: np.ndarray, y: np.ndarray) -> np.ndarray:
    """CRPS of the sample distribution S [N, ...] at y [...]: E|X - y| - E|X - X'| / 2."""
    N = S.shape[0]
    i = np.arange(1, N + 1).reshape((-1,) + (1,) * (S.ndim - 1))
    return np.mean(np.abs(S - y), 0) - np.sum((2 * i - N - 1) * np.sort(S, 0), 0) / N ** 2


def summarise(S: np.ndarray, y: np.ndarray) -> dict:
    ok = np.isfinite(y)
    crps = np.where(ok, crps_samples(S, np.nan_to_num(y)), np.nan)
    return {"mu": S.mean(0).tolist(), "q05": np.quantile(S, 0.05, 0).tolist(),
            "q95": np.quantile(S, 0.95, 0).tolist(), "crps": crps.tolist()}


def run_fold(data: dict, j: int) -> dict:
    dates = data["dates"]
    train, test = mn.fold_indices(dates, j)
    last = int(data["t"][train[-1]] + max(mn.HORIZONS))  # training targets end here, as in the anchor
    print(f"fold {j}: train months to {data['t'][train[-1]]} (+12), test {dates[test[0]]:%Y-%m}..{dates[test[-1]]:%Y-%m}",
          flush=True)
    post, st, info, diag = fit(data, last, seed=j)
    print(f"fold {j}: {diag}", flush=True)
    rng = np.random.default_rng(100 + j)
    t, y = data["t"][test], data["Y"][test]
    out = {"fold": j, "test_dates": [f"{d:%Y-%m}" for d in dates[test]], "names": data["names"],
           "groups": data["groups"], "y": y.tolist(), "diagnostics": diag, "modes": {}}
    out["modes"]["whatif"] = summarise(simulate(post, st, info, data, t, data["OIL"][test][None], rng), y)
    fut = oil_paths(data, st, last, t, len(post["a"]), rng)
    out["modes"]["forecast"] = summarise(simulate(post, st, info, data, t, fut, rng), y)
    return out


def responses(post: dict, st: Stats, info: dict, shock: float) -> np.ndarray:
    """Posterior change of each series after 1..12 months for a one-off oil move of `shock` (log)
    in the first month from a calm baseline (no other oil change): [N, K, 12]. The noise and the
    series' own drift cancel between shocked and baseline paths, so only B, alpha and rho matter."""
    z = shock / st.xs
    g = z * (1 + post["alpha"]) if z > 0 else z * (1 - post["alpha"])  # [N, K]
    N, K = post["a"].shape
    eff, prev, cum = np.zeros((N, K, mn.OIL_AHEAD)), np.zeros((N, K)), np.zeros((N, K))
    for j in range(mn.OIL_AHEAD):
        cur = post["rho"] * prev + post["B"][:, :, j] * g
        cum = cum + cur * st.ys
        eff[:, :, j], prev = cum, cur
    return eff


def run_final(data: dict) -> dict:
    last = len(data["oil_m"]) - 1
    post, st, info, diag = fit(data, last, seed=99)
    print(f"final: {diag}", flush=True)
    res = {}
    for label, shock in (("up10", np.log(1.10)), ("down10", np.log(0.90))):
        e = responses(post, st, info, shock)
        res[label] = {"mean": e.mean(0).tolist(), "q05": np.quantile(e, 0.05, 0).tolist(),
                      "q95": np.quantile(e, 0.95, 0).tolist(), "p_positive": (e > 0).mean(0).tolist()}
    q = lambda v: {"mean": v.mean(0).tolist(), "q05": np.quantile(v, 0.05, 0).tolist(),  # noqa: E731
                   "q95": np.quantile(v, 0.95, 0).tolist()}
    return {"keys": info["keys"], "groups": info["groups"], "diagnostics": diag, "responses": res,
            "params": {k: q(post[k]) for k in ("alpha", "phi", "rho", "nu")},
            "data_to": f"{data['dates'][-1] + pd.DateOffset(months=mn.OIL_AHEAD):%Y-%m}"}


# --- report ----------------------------------------------------------------------------------

def load(name: str) -> dict | None:
    p = RUNS / name
    return json.loads(p.read_text()) if p.exists() else None


def skill_table(folds: list[tuple[dict, dict, dict | None]], groups: list[str], H: np.ndarray) -> list[str]:
    """Rows of skill vs the v1 climatology by group x horizon, for the Bayesian modes and references."""
    def stack(get):
        return np.vstack([np.array(get(b, v, a), float) for b, v, a in folds])

    clim = stack(lambda b, v, a: v["models"]["climatology"]["crps"])
    cols = {"Bayes what-if": stack(lambda b, v, a: b["modes"]["whatif"]["crps"]),
            "Bayes forecast": stack(lambda b, v, a: b["modes"]["forecast"]["crps"]),
            "v1 nn_mean (what-if)": stack(lambda b, v, a: v["models"]["nn_mean"]["crps"])}
    if all(a is not None for _, _, a in folds):
        cols["anchored nn_mean (what-if)"] = stack(lambda b, v, a: a["models"]["nn_mean"]["crps"])
        cols["anchored climatology (what-if)"] = stack(lambda b, v, a: a["models"]["climatology"]["crps"])
    g = np.array(groups)
    rows = ["| Target | h | " + " | ".join(cols) + " |", "|---|---|" + "---|" * len(cols)]
    for grp in ("inflation", "unemployment", "rate", "cost"):
        for h in [*mn.HORIZONS, "all"]:
            c = np.where((g == grp) & ((H == h) if h != "all" else True))[0]
            sk = [1 - np.nanmean(np.nanmean(v[:, c], 0) / np.nanmean(clim[:, c], 0)) for v in cols.values()]
            b = "**" if h == "all" else ""
            rows.append(f"| {grp} | {h} | " + " | ".join(f"{b}{s:+.3f}{b}" for s in sk) + " |")
    return rows


def converged(d: dict) -> bool:
    return d["max_r_hat"] <= 1.05 and d["min_ess"] >= 100


def report() -> None:
    folds, failed = [], []
    for j in range(mn.FOLDS):
        b, v = load(f"bayes-fold-{j}.json"), load(f"fold-{j}.json")
        if b and v:
            assert b["test_dates"] == v["test_dates"], f"fold {j}: origins differ from fold-{j}.json"
            (folds if converged(b["diagnostics"]) else failed).append((b, v, load(f"fold-anchored-{j}.json")))
    if not folds:
        raise SystemExit("no converged runs/macro/bayes-fold-*.json yet")
    names, groups = folds[0][0]["names"], folds[0][0]["groups"]
    H = np.array([int(n.split("@")[1]) for n in names])
    n_orig = sum(len(b["test_dates"]) for b, _, _ in folds)
    out = [
        "# Bayesian oil pass-through (MCMC): results", "",
        f"_Generated by `experiments/macro_bayes.py report` on {datetime.now(UTC).date().isoformat()} from "
        f"{len(folds)} forward-chaining folds ({folds[0][0]['test_dates'][0]}..{folds[-1][0]['test_dates'][-1]}, "
        f"{n_orig} forecast origins), the same folds and data as `notes/macro-nn-results.md` (inputs: "
        "`notes/macro-panel.md`, fetched 2026-10-24). The data are real; the only simulated inputs are the "
        "oil paths of the forecast mode (block bootstrap of each fold's training months)._", "",
        "Skill = 1 − CRPS / CRPS of the v1 climatology (training mean and spread), averaged over the outputs "
        "in the group; 0 is no better than climatology. **What-if** forecasts are given the oil path that "
        "happened; **forecast** knows nothing after the origin. Every column is scored on the same folds.", "",
        *([f"**Excluded:** fold(s) {[b['fold'] for b, _, _ in failed]} (test "
           + ", ".join(f"{b['test_dates'][0]}..{b['test_dates'][-1]}" for b, _, _ in failed)
           + ") did not converge (see Sampler health), so every column here leaves them out.", ""] if failed else []),
        "## Skill by horizon", "", *skill_table(folds, groups, H), "",
        "## Calibration: share of outcomes inside the central 90% interval (target 90%)", "",
        "| Target | Bayes what-if | Bayes forecast |", "|---|---|---|"]
    g = np.array(groups)
    for grp in ("inflation", "unemployment", "rate", "cost"):
        c = np.where(g == grp)[0]
        cov = []
        for mode in ("whatif", "forecast"):
            y = np.vstack([np.array(b["y"], float)[:, c] for b, _, _ in folds])
            lo = np.vstack([np.array(b["modes"][mode]["q05"])[:, c] for b, _, _ in folds])
            hi = np.vstack([np.array(b["modes"][mode]["q95"])[:, c] for b, _, _ in folds])
            ok = np.isfinite(y)
            cov.append(np.mean(((y >= lo) & (y <= hi))[ok]))
        out.append(f"| {grp} | {cov[0]:.0%} | {cov[1]:.0%} |")
    # the 2026 closure: the last fold's origins whose 12-month targets fall in it
    b, v, a = folds[-1]
    if b["fold"] == mn.FOLDS - 1:
        out += ["", "## The 2026 Hormuz closure (12 months ahead, from the last fold)", "",
                "| Origin | Output | Actual | Bayes what-if (90%) | Bayes forecast (90%) | anchored nn_mean | v1 nn_mean |",
                "|---|---|---|---|---|---|---|"]
        for t in ("2025-03", "2025-06", "2025-09"):
            if t not in b["test_dates"]:
                continue
            i = b["test_dates"].index(t)
            for nm in ("us_cpi@12", "uk_cpi@12", "ea_cpi@12", "ind_gasdesw@12", "ind_djfuelusgulf@12"):
                k = names.index(nm)
                y = b["y"][i][k]
                cell = lambda m: f"{b['modes'][m]['mu'][i][k]:+.1f} ({b['modes'][m]['q05'][i][k]:+.1f}..{b['modes'][m]['q95'][i][k]:+.1f})"  # noqa: E731
                anch = f"{a['models']['nn_mean']['mu'][i][k]:+.1f}" if a else "-"
                out.append(f"| {t} | {nm} | {'n/a' if y is None or y != y else f'{y:+.1f}'} | {cell('whatif')} | "
                           f"{cell('forecast')} | {anch} | {v['models']['nn_mean']['mu'][i][k]:+.1f} |")
    bad = [bb["fold"] for bb, _, _ in failed]
    out += ["", "## Sampler health", "",
            f"**Fit health:** {'every fold converged (max R-hat ≤ 1.05, min ESS ≥ 100)' if not bad else f'folds {bad} did NOT converge and are left out above'}.",
            "", "| Fold | Seconds | Divergences | Max R-hat | Min ESS | Tree-depth hits |", "|---|---|---|---|---|---|"]
    for bb, _, _ in sorted(folds + failed, key=lambda f: f[0]["fold"]):
        d = bb["diagnostics"]
        out.append(f"| {bb['fold']} | {d['seconds']} | {d['divergences']} | {d['max_r_hat']} | {d['min_ess']} | {d['tree_depth_hits']} |")
    fin = load("bayes-final.json")
    if fin:
        keys = fin["keys"]
        r_up, r_dn = fin["responses"]["up10"], fin["responses"]["down10"]
        out += ["", "## Posterior response to a one-off ±10% Brent move (fit on all data)", "",
                f"Change after 3 and 12 months, in the target's units (% of the price level; pp for rates and "
                f"unemployment), posterior mean and 90% interval. Sampler: {fin['diagnostics']}.", "",
                "| Series | +10%, 3 m | +10%, 12 m | −10%, 12 m | P(effect > 0), +10% | asymmetry α | vol-state φ |",
                "|---|---|---|---|---|---|---|"]
        p = fin["params"]
        # The interface for the what-if (World view, household chain): one row per series x shock x month.
        lines = ["series,group,shock,months_ahead,mean,q05,q95,p_positive,unit,source,fitted_to,generated"]
        gen = datetime.now(UTC).date().isoformat()
        for k, key in enumerate(keys):
            unit = "pp" if fin["groups"][k] in ("unemployment", "rate") else "% of price level"
            for label, r in (("brent_up_10pct", r_up), ("brent_down_10pct", r_dn)):
                for m in range(mn.OIL_AHEAD):
                    lines.append(f"{key},{fin['groups'][k]},{label},{m + 1},{r['mean'][k][m]:.4f},{r['q05'][k][m]:.4f},"
                                 f"{r['q95'][k][m]:.4f},{r['p_positive'][k][m]:.3f},{unit},"
                                 f"experiments/macro_bayes.py (FRED/ONS/Eurostat via notes/macro-panel.md),"
                                 f"{fin['data_to'].split(' ')[0]},{gen}")
        (NOTES / "macro-bayes-responses.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        for k, key in enumerate(keys):
            c = lambda r, m: f"{r['mean'][k][m]:+.2f} ({r['q05'][k][m]:+.2f}..{r['q95'][k][m]:+.2f})"  # noqa: E731
            out.append(f"| {key} | {c(r_up, 2)} | {c(r_up, 11)} | {c(r_dn, 11)} | {r_up['p_positive'][k][11]:.2f} | "
                       f"{p['alpha']['mean'][k]:+.2f} ({p['alpha']['q05'][k]:+.2f}..{p['alpha']['q95'][k]:+.2f}) | "
                       f"{p['phi']['mean'][k]:+.2f} |")
    (NOTES / "macro-bayes-results.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {NOTES / 'macro-bayes-results.md'}")


# --- entry -----------------------------------------------------------------------------------

def main() -> None:
    global QUICK
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("check", "fold", "final", "report"))
    p.add_argument("j", nargs="?", type=int, default=0)
    a = p.parse_args()
    if a.cmd == "report":
        return report()
    data = mn.make_dataset(mn.V1_BLOCKS)
    RUNS.mkdir(parents=True, exist_ok=True)
    meta = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "job": os.environ.get("SLURM_JOB_ID")}
    if a.cmd == "check":
        QUICK = True
        out = run_fold(data, mn.FOLDS - 1)
        print({m: float(np.nanmean(v["crps"])) for m, v in out["modes"].items()})
        return
    if a.cmd == "fold":
        out = run_fold(data, a.j) | {"meta": meta}
        path = RUNS / f"bayes-fold-{a.j}.json"
    else:
        out = run_final(data) | {"meta": meta}
        path = RUNS / "bayes-final.json"
    path.write_text(json.dumps(out))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
