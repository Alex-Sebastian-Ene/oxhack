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
    e[s,k] ~ Student-t(nu[k], 0, floor[k] + sigma[k] exp(phi[k] v[s] + h[s,g(k)]))

- x: monthly log change of Brent (standardised); x+ and x- are its rises and falls. alpha > 0
  means rises pass through more strongly than falls ("rockets and feathers").
- B: lag coefficients (0..12 months, or 0..2 for fuel and freight, as in the anchor), pooled
  towards a mean per target group and lag length: short series borrow strength from their group.
- rho: momentum in the series' own monthly change, which is what a short-horizon forecast uses.
- v: recent oil volatility (log mean |x| over 3 months, standardised), so the band widens in oil
  turmoil instead of everywhere.
- Volatility beyond oil, so the band can widen for other reasons (2021-23 inflation):
  - `--vol cdv`: h, one drifting log-volatility per target group, a random walk, as in the common
    drifting volatility of Carriero, Clark & Marcellino (2016). Its latent states make NUTS slow
    (every step hits the tree-depth limit, ~8 min a fold on 2 cores); run it on Iridis.
  - `--vol own`: psi[k] times each series' own recent volatility (log EWMA of its past |changes|,
    standardised). Observation-driven, like GARCH, so there is nothing latent to sample.

Forecasts are simulated month by month from each series' last published month, over posterior
draws, so they carry parameter uncertainty, fat tails and the volatility state. Two oil modes are
scored on the same forward-chaining folds as macro_nn.py:
    whatif    the oil path that happened (the what-if, as in macro_nn.py)
    forecast  a genuine forecast: nothing after the origin is known. Oil paths are a block
              bootstrap of training months, centred on the WTI futures curve's slope (EIA, to
              2024-04; no drift after) and scaled to the oil-options implied volatility at the
              origin (CBOE OVX via FRED, from 2007-05; realised volatility before)

    uv run experiments/macro_bayes.py check                # tiny end-to-end run
    uv run experiments/macro_bayes.py fold 3 [--vol cdv]   # one fold -> runs/macro/bayes[-cdv]-fold-3.json
    uv run experiments/macro_bayes.py final [--vol cdv]    # all data: posterior oil-shock responses
    uv run experiments/macro_bayes.py benchmarks           # random walk, surveys, point-estimate versions
    uv run experiments/macro_bayes.py report               # notes/macro-bayes-results.md + responses CSV
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
from scipy.stats import norm  # noqa: E402

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
# Error-scale floor, in each series' training sd, added after the volatility terms so it holds in
# calm months too. Policy rates move in discrete steps and sit still for years (the ECB deposit
# rate was flat 2016-2022), so a continuous model needs a wider floor there, or drift and momentum
# trade off in two separate modes (fold 6 had R-hat 17 on ea_rate with 0.05).
SIGMA_FLOOR = {"rate": 0.2}
SIGMA_FLOOR_DEFAULT = 0.05
GROUPS = ("inflation", "unemployment", "rate", "cost")
OWN_LAMBDA, OWN_FLOOR = 0.9, 0.05  # `--vol own`: EWMA weight on the series' own past |change|, and log floor
OWN_MAX = 0.9  # `--vol own`: bound on the feedback of log volatility on itself (stationarity)
LOG_SCALE_CLIP = (-6.0, 4.0)  # volatility terms of the log scale, clipped in fitting and simulation alike
SCENARIO = 36  # months of oil-shock responses written for the what-if; 13..36 are untested scenarios
QUICK = False


# --- data ------------------------------------------------------------------------------------

def series_info(data: dict) -> dict:
    """Per target series: group, publication lag, oil lags, pooling cluster (group x lags), scale floor."""
    reg = {s.key: s for s in md.registry(md.BLOCKS)}
    keys = data["target_keys"]
    groups = [reg[k].target for k in keys]
    clusters = sorted(set(zip(groups, data["target_lags"])))
    return {"keys": keys, "groups": groups, "pub_lag": np.array([reg[k].lag for k in keys]),
            "lags": np.array(data["target_lags"]),
            "cluster": np.array([clusters.index(c) for c in zip(groups, data["target_lags"])]),
            "clusters": [f"{g}/{n}" for g, n in clusters],
            "vgroup": np.array([GROUPS.index(g) for g in groups]),
            "floor": np.array([SIGMA_FLOOR.get(g, SIGMA_FLOOR_DEFAULT) for g in groups])}


class Stats:
    """Standardisation of oil, volatility state and targets from training months only."""

    def __init__(self, data: dict, last_month: int) -> None:
        self.last = last_month
        x = data["oil_m"][1:last_month + 1]
        self.xm, self.xs = 0.0, float(np.nanstd(x))
        self.x2 = float(np.nanmean(x ** 2))
        lv = log_vol(np.nan_to_num(data["oil_m"]) / self.xs)[13:last_month + 1]
        self.vm, self.vs = float(lv.mean()), float(lv.std())
        y = data["dM"][13:last_month + 1]
        self.ym, self.ys = np.nanmean(y, 0), np.nanstd(y, 0) + 1e-8
        lu = np.log(own_ewma((data["dM"] - self.ym) / self.ys) + OWN_FLOOR)[13:last_month + 1]
        self.um, self.us = np.nanmean(lu, 0), np.nanstd(lu, 0) + 1e-8


def log_vol(z: np.ndarray) -> np.ndarray:
    a = np.abs(z)
    return np.log((a + np.r_[0, a[:-1]] + np.r_[0, 0, a[:-2]]) / 3 + VOL_FLOOR)


def own_ewma(y: np.ndarray) -> np.ndarray:
    """Each series' own recent volatility [M, K]: EWMA of |y| over months before s (so known at s);
    a missing month leaves it unchanged. Observation-driven, like GARCH: no latent states to sample."""
    e = np.ones(y.shape)
    for s in range(1, len(y)):
        prev = np.abs(y[s - 1])
        e[s] = np.where(np.isfinite(prev), OWN_LAMBDA * e[s - 1] + (1 - OWN_LAMBDA) * np.nan_to_num(prev), e[s - 1])
    return e


def design(data: dict, st: Stats, last_month: int) -> dict:
    """Training arrays: lagged rises/falls [S, LAGS], volatility state [S], y and y[s-1] [S, K]."""
    z = np.nan_to_num(data["oil_m"]) / st.xs
    lag = np.stack([np.concatenate([np.zeros(l), z[:len(z) - l]]) for l in range(LAGS)], 1)
    v = (log_vol(z) - st.vm) / st.vs
    y = (data["dM"] - st.ym) / st.ys
    u = (np.log(own_ewma(y) + OWN_FLOOR) - st.um) / st.us
    rows = np.arange(13, last_month + 1)  # full oil lags behind every training month
    return {"Xp": np.maximum(lag, 0)[rows], "Xn": np.minimum(lag, 0)[rows], "v": v[rows],
            "y": y[rows], "yprev": y[rows - 1], "u": u[rows]}


def month_index(data: dict) -> pd.DatetimeIndex:
    """Calendar month of every monthly array position (data['oil_m'], data['dM'])."""
    start = data["dates"][0] - pd.DateOffset(months=int(data["t"][0]))
    return pd.date_range(start, periods=len(data["oil_m"]), freq="MS")


def market_inputs(data: dict) -> dict:
    """Market prices for the forecast mode's oil paths, aligned to the monthly arrays.

    ovx:   CBOE crude-oil implied volatility (FRED OVXCLS, monthly mean, annualised %), from 2007-05.
    drift: expected Brent log change in months 1..12 after each month, from the slope of the NYMEX
           WTI futures curve (EIA RCLC1-4 monthly means: front month against spot, then contract 2
           against 1, ...); zero beyond 4 months and where EIA has no data (after 2024-04)."""
    idx = month_index(data)
    ovx = md.fetch_fred("OVXCLS").reindex(idx).values
    spot = md.fetch_fred("DCOILWTICO").reindex(idx).values
    fut = []
    for k in range(1, 5):
        p = md._get(f"https://www.eia.gov/dnav/pet/hist_xls/RCLC{k}m.xls", md.RAW / f"eia_RCLC{k}m.xls")
        df = pd.read_excel(p, sheet_name="Data 1", skiprows=2)
        s = pd.Series(df.iloc[:, 1].astype(float).values, index=pd.to_datetime(df.iloc[:, 0]))
        fut.append(s.resample("MS").mean().reindex(idx).values)
    curve = np.log(np.column_stack([spot, *fut]))
    drift = np.zeros((len(idx), mn.OIL_AHEAD))
    drift[:, :4] = np.diff(curve, axis=1)
    drift[~np.isfinite(drift)] = 0.0
    files = [md.RAW / n for n in ("fred_OVXCLS.csv", "eia_RCLC1m.xls")]
    fetched = min(datetime.fromtimestamp(f.stat().st_mtime, UTC).date().isoformat() for f in files)
    return {"ovx": ovx, "drift": drift, "has_futures": np.isfinite(curve).all(1), "fetched": fetched}


# --- model -----------------------------------------------------------------------------------

def model(Xp, Xn, v, yprev, y, u, lagmask, cluster, n_clusters, floor, vgroup, n_vgroups, own, own_us):
    S, K = y.shape
    mu = numpyro.sample("mu", dist.Normal(0, 0.5).expand([n_clusters, LAGS]).to_event(2))
    tau = numpyro.sample("tau", dist.HalfNormal(0.2).expand([n_clusters, 1]).to_event(2))
    bz = numpyro.sample("bz", dist.Normal(0, 1).expand([K, LAGS]).to_event(2))
    B = numpyro.deterministic("B", (mu[cluster] + tau[cluster] * bz) * lagmask)  # non-centred pooling
    a = numpyro.sample("a", dist.Normal(0, 1).expand([K]).to_event(1))
    rho = numpyro.deterministic("rho", 0.95 * jnp.tanh(numpyro.sample("rho_raw", dist.Normal(0, 0.5).expand([K]).to_event(1))))
    alpha = numpyro.deterministic("alpha", 0.9 * jnp.tanh(numpyro.sample("alpha_raw", dist.Normal(0, 0.5).expand([K]).to_event(1))))
    sigma_raw = numpyro.sample("sigma_raw", dist.HalfNormal(1).expand([K]).to_event(1))
    numpyro.deterministic("sigma", floor + sigma_raw)  # the scale at average volatility
    phi = numpyro.sample("phi", dist.Normal(0, 0.5).expand([K]).to_event(1))
    nu = numpyro.deterministic("nu", NU_MIN + numpyro.sample("nu_m", dist.Gamma(2, 0.1).expand([K]).to_event(1)))
    logs = phi * v[:, None]
    if n_vgroups:  # common drifting volatility per target group (random walk, non-centred)
        omega = numpyro.sample("omega", dist.HalfNormal(0.1).expand([n_vgroups]).to_event(1))
        eps = numpyro.sample("h_eps", dist.Normal(0, 1).expand([S, n_vgroups]).to_event(2))
        h = numpyro.deterministic("h", jnp.cumsum(eps * omega, 0))
        logs = logs + h[:, vgroup]
    if own:  # the series' own recent volatility (EWMA of past |changes|), observation-driven
        # psi / us is the feedback of log volatility on itself; keeping it below 0.9 keeps it
        # stationary, otherwise a big simulated change raises the scale, which raises the next change...
        psi = numpyro.deterministic("psi", OWN_MAX * own_us * jnp.tanh(numpyro.sample("psi_raw", dist.Normal(0, 1).expand([K]).to_event(1))))
        logs = logs + psi * u
    logs = jnp.clip(logs, *LOG_SCALE_CLIP)
    ok = jnp.isfinite(y) & jnp.isfinite(yprev)
    m = a + rho * jnp.nan_to_num(yprev) + (Xp @ B.T) * (1 + alpha) + (Xn @ B.T) * (1 - alpha)
    # The floor keeps a series that sits still for years (policy rates at zero: most monthly changes
    # are exactly 0) from collapsing its scale towards 0, which strands chains in that spike.
    scale = floor + sigma_raw * jnp.exp(logs)
    with numpyro.handlers.mask(mask=ok):
        numpyro.sample("y", dist.StudentT(nu, m, scale), obs=jnp.nan_to_num(y))


KEEP = ("B", "a", "rho", "alpha", "sigma", "sigma_raw", "phi", "nu", "omega", "psi")
SITES = ("mu", "tau", "bz", "a", "rho_raw", "alpha_raw", "sigma_raw", "phi", "nu_m", "omega", "h_eps", "psi_raw")


def fit(data: dict, last_month: int, seed: int = 0, vol: str = "oil") -> tuple[dict, Stats, dict, dict]:
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
             floor=jnp.asarray(info["floor"]), vgroup=jnp.asarray(info["vgroup"]),
             n_vgroups=len(GROUPS) if vol == "cdv" else 0, own=vol == "own", own_us=jnp.asarray(st.us))
    grouped = mcmc.get_samples(group_by_chain=True)
    # every sampled site, hyperparameters included (they mix slowest in a non-centred hierarchy)
    summ = numpyro.diagnostics.summary({k: np.asarray(grouped[k]) for k in SITES if k in grouped})
    rhat = max(float(np.nanmax(s["r_hat"])) for s in summ.values())
    ess = min(float(np.nanmin(s["n_eff"])) for s in summ.values())
    extra = mcmc.get_extra_fields()
    diag = {"seconds": round(time.time() - t0, 1), "chains": CHAINS, "warmup": warm, "samples": samp, "vol": vol,
            "divergences": int(np.sum(extra["diverging"])), "max_r_hat": round(rhat, 3), "min_ess": round(ess, 1),
            "tree_depth_hits": int(np.sum(np.asarray(extra["num_steps"]) >= 2 ** TREE_DEPTH - 1)),
            "months": int(np.isfinite(d["y"]).any(1).sum())}
    samples = mcmc.get_samples()
    post = {k: np.asarray(v) for k, v in samples.items() if k in KEEP}
    if "h" in samples:
        post["h_last"] = np.asarray(samples["h"])[:, -1, :]  # drifting volatility at the last training month
    n = len(post["a"])
    pick = np.random.default_rng(seed).choice(n, size=min(DRAWS if not QUICK else 50, n), replace=False)
    return {k: v[pick] for k, v in post.items()}, st, info, diag


# --- forecasts -------------------------------------------------------------------------------

def oil_paths(data: dict, st: Stats, last_month: int, t: np.ndarray, n: int, rng, market: dict | None = None) -> np.ndarray:
    """Simulated monthly Brent log changes after each origin [n, len(t), 12]: block bootstrap of the
    training months, demeaned, scaled to the volatility at the origin relative to the training
    average (the ratio decays back to 1 over the path), plus the futures-curve drift.

    The volatility ratio is the implied one (OVX at the origin against its training-month mean)
    when at least 12 training months of OVX exist, otherwise the realised one (last 3 months)."""
    x = data["oil_m"][1:last_month + 1]
    x = x[np.isfinite(x)] - np.nanmean(x)
    starts = rng.integers(0, len(x) - BLOCK + 1, size=(n, len(t), -(-mn.OIL_AHEAD // BLOCK)))
    path = np.concatenate([x[starts + b][..., None] for b in range(BLOCK)], -1).reshape(n, len(t), -1)[..., :mn.OIL_AHEAD]
    recent = np.array([np.nanmean(data["oil_m"][max(i - 2, 1):i + 1] ** 2) for i in t])
    ratio = np.sqrt(recent / st.x2)
    drift = np.zeros((len(t), mn.OIL_AHEAD))
    if market is not None:
        train_ovx = market["ovx"][1:last_month + 1]
        if np.isfinite(train_ovx).sum() >= 12:
            implied = market["ovx"][t] / np.nanmean(train_ovx)
            ratio = np.where(np.isfinite(implied), implied, ratio)
        drift = market["drift"][t]
    ratio = np.clip(ratio, 0.5, 3.0)
    decay = 0.8 ** np.arange(1, mn.OIL_AHEAD + 1)
    return path * (1 + (ratio[:, None] - 1) * decay[None, :])[None] + drift[None]


def simulate(post: dict, st: Stats, info: dict, data: dict, t: np.ndarray, future: np.ndarray, rng,
             noise: bool = True) -> np.ndarray:
    """Draws of every output (target-major, horizon-minor, as data['names']) at origins t (month
    indices): [N, len(t), outputs]. future: oil log changes after each origin, [N or 1, len(t), 12].

    Each series is simulated from its last published month (t - publication lag), so months that
    have happened but are not yet published are nowcast, as a forecaster at the end of month t would.
    With drifting volatility, the group volatilities carry on as random walks from the last training
    month, so a later origin in a test block is less sure of the current volatility."""
    N, K = len(post["a"]), len(info["keys"])
    O, pmax, H = len(t), int(info["pub_lag"].max()), mn.OIL_AHEAD
    z_all = np.nan_to_num(data["oil_m"]) / st.xs
    y_all = (data["dM"] - st.ym) / st.ys
    zf = np.broadcast_to(future / st.xs, (N, O, H))
    B, a, rho, alpha = post["B"], post["a"], post["rho"], post["alpha"]
    sig, phi, nu = post.get("sigma_raw", post["sigma"]), post["phi"], post["nu"]
    floor = info.get("floor", np.zeros(K))
    # buffer of the last LAGS oil changes before the first simulated month, newest first
    s0 = t - pmax + 1
    buf = np.stack([z_all[s0 - 1 - l] for l in range(LAGS)], -1)[None].repeat(N, 0)  # [N, O, LAGS]
    yprev = np.nan_to_num(y_all[s0 - 1])[None].repeat(N, 0)  # [N, O, K]
    cdv = "omega" in post and noise
    if cdv:
        om = post["omega"][:, None, :]  # [N, 1, G]
        gap = np.maximum(s0 - 1 - st.last, 0)[None, :, None]  # months from the end of training
        hcur = post["h_last"][:, None, :] + np.sqrt(gap) * om * rng.standard_normal((N, O, om.shape[-1]))
    own = "psi" in post and noise
    if own:  # each series' own volatility, from published months, then updated with the simulated ones
        e = own_ewma(y_all)[s0][None].repeat(N, 0)  # [N, O, K]
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
            logs = phi[:, None] * v[..., None]
            if cdv:
                hcur = hcur + om * rng.standard_normal(hcur.shape)
                logs = logs + hcur[..., info["vgroup"]]
            if own:
                logs = logs + post["psi"][:, None, :] * (np.log(e + OWN_FLOOR) - st.um) / st.us
            logs = np.clip(logs, *LOG_SCALE_CLIP)
            m = m + rng.standard_t(nu[:, None, :], size=(N, O, K)) * (floor + sig[:, None] * np.exp(logs))
        known = j <= -info["pub_lag"]  # [K]: this month is already published for these series
        if known.any():
            obs = y_all[t + j]
            m = np.where(known & np.isfinite(obs)[None], np.nan_to_num(obs)[None], m)
        yprev = m
        if own:
            e = OWN_LAMBDA * e + (1 - OWN_LAMBDA) * np.abs(m)
        if j >= 1:
            cum = cum + m * st.ys + st.ym
            for hi, h in enumerate(mn.HORIZONS):
                if j == h:
                    out[..., hi] = cum
    return out.reshape(N, O, K * len(mn.HORIZONS))


def crps_samples(S: np.ndarray, y: np.ndarray) -> np.ndarray:
    """CRPS of the sample distribution S [N, ...] at y [...]: E|X - y| - E|X - X'| / 2 (the plain
    sample form, which overstates CRPS by E|X - X'| / 2N, about 0.1% at N = 400)."""
    N = S.shape[0]
    i = np.arange(1, N + 1).reshape((-1,) + (1,) * (S.ndim - 1))
    return np.mean(np.abs(S - y), 0) - np.sum((2 * i - N - 1) * np.sort(S, 0), 0) / N ** 2


def gaussian_crps(mu, sd, y):
    z = (y - mu) / sd
    return sd * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / np.sqrt(np.pi))


def summarise(S: np.ndarray, y: np.ndarray) -> dict:
    ok = np.isfinite(y)
    crps = np.where(ok, crps_samples(S, np.nan_to_num(y)), np.nan)
    return {"mu": S.mean(0).tolist(), "q05": np.quantile(S, 0.05, 0).tolist(),
            "q95": np.quantile(S, 0.95, 0).tolist(), "crps": crps.tolist()}


def fold_window(data: dict, j: int) -> tuple[np.ndarray, np.ndarray, int]:
    train, test = mn.fold_indices(data["dates"], j)
    return train, test, int(data["t"][train[-1]] + max(mn.HORIZONS))  # training months end here, as in the anchor


def run_fold(data: dict, j: int, vol: str = "oil", market: dict | None = None) -> dict:
    dates = data["dates"]
    train, test, last = fold_window(data, j)
    print(f"fold {j} [{vol}]: train months to {last}, test {dates[test[0]]:%Y-%m}..{dates[test[-1]]:%Y-%m}", flush=True)
    post, st, info, diag = fit(data, last, seed=j, vol=vol)
    print(f"fold {j}: {diag}", flush=True)
    rng = np.random.default_rng(100 + j)
    t, y = data["t"][test], data["Y"][test]
    out = {"fold": j, "test_dates": [f"{d:%Y-%m}" for d in dates[test]], "names": data["names"],
           "groups": data["groups"], "y": y.tolist(), "diagnostics": diag, "modes": {}}
    out["modes"]["whatif"] = summarise(simulate(post, st, info, data, t, data["OIL"][test][None], rng), y)
    fut = oil_paths(data, st, last, t, len(post["a"]), rng, market)
    out["modes"]["forecast"] = summarise(simulate(post, st, info, data, t, fut, rng), y)
    if market is not None:
        out["market"] = {"origins_with_futures": int(market["has_futures"][t].sum()),
                         "origins_with_ovx": int(np.isfinite(market["ovx"][t]).sum()), "fetched": market["fetched"]}
    return out


def responses(post: dict, st: Stats, info: dict, shock: float, months: int = SCENARIO) -> np.ndarray:
    """Posterior change of each series after 1..months months for a one-off oil move of `shock`
    (log) in the first month from a calm baseline (no other oil change): [N, K, months]. The noise
    and the series' own drift cancel between shocked and baseline paths, so only B, alpha and rho
    matter. Past 12 months the effect is the momentum carrying on, which no fold has tested."""
    z = shock / st.xs
    g = z * (1 + post["alpha"]) if z > 0 else z * (1 - post["alpha"])  # [N, K]
    N, K = post["a"].shape
    eff, prev, cum = np.zeros((N, K, months)), np.zeros((N, K)), np.zeros((N, K))
    for j in range(months):
        cur = post["rho"] * prev + (post["B"][:, :, j] * g if j < LAGS else 0.0)
        cum = cum + cur * st.ys
        eff[:, :, j], prev = cum, cur
    return eff


def run_final(data: dict, vol: str = "oil") -> dict:
    last = len(data["oil_m"]) - 1
    post, st, info, diag = fit(data, last, seed=99, vol=vol)
    print(f"final [{vol}]: {diag}", flush=True)
    res = {}
    for label, shock in (("up10", np.log(1.10)), ("down10", np.log(0.90))):
        e = responses(post, st, info, shock)
        res[label] = {"mean": e.mean(0).tolist(), "q05": np.quantile(e, 0.05, 0).tolist(),
                      "q95": np.quantile(e, 0.95, 0).tolist(), "p_positive": (e > 0).mean(0).tolist()}
    q = lambda v: {"mean": v.mean(0).tolist(), "q05": np.quantile(v, 0.05, 0).tolist(),  # noqa: E731
                   "q95": np.quantile(v, 0.95, 0).tolist()}
    return {"keys": info["keys"], "groups": info["groups"], "diagnostics": diag, "responses": res,
            "params": {k: q(post[k]) for k in ("alpha", "phi", "rho", "nu", "omega", "psi") if k in post},
            "data_to": f"{data['dates'][-1] + pd.DateOffset(months=mn.OIL_AHEAD):%Y-%m}"}


# --- benchmarks ------------------------------------------------------------------------------

def point_post(d: dict, info: dict, use_oil: bool, n: int) -> dict:
    """Least-squares version of the mean equation (momentum, plus symmetric oil lags if use_oil),
    with Gaussian errors at the residual sd: the model without pooling, asymmetry, fat tails,
    volatility terms or parameter uncertainty."""
    K = len(info["keys"])
    post = {"B": np.zeros((n, K, LAGS)), "a": np.zeros((n, K)), "rho": np.zeros((n, K)), "alpha": np.zeros((n, K)),
            "sigma": np.zeros((n, K)), "phi": np.zeros((n, K)), "nu": np.full((n, K), 1e6)}
    X = d["Xp"] + d["Xn"]
    for k in range(K):
        ok = np.isfinite(d["y"][:, k]) & np.isfinite(d["yprev"][:, k])
        L = info["lags"][k] + 1 if use_oil else 0
        A = np.column_stack([np.ones(ok.sum()), d["yprev"][ok, k], X[ok, :L]])
        w, *_ = np.linalg.lstsq(A, d["y"][ok, k], rcond=None)
        post["a"][:, k], post["rho"][:, k], post["sigma"][:, k] = w[0], w[1], (d["y"][ok, k] - A @ w).std()
        post["B"][:, k, :L] = w[2:]
    return post


def run_benchmarks(data: dict) -> dict:
    """Per fold, CRPS [origins, outputs] of:
      ar, ar_oil  least-squares versions of the mean equation (what-if: given the oil path)
      rw          inflation runs at its last published 12-month pace (forecast)
      cleveland   US CPI, 12 months: Cleveland Fed 1-year expected inflation (FRED EXPINF1YR) (forecast)
      michigan    US CPI, 12 months: Michigan 1-year inflation expectations (FRED MICH) (forecast)
    Point benchmarks get a Gaussian band with the sd of their own errors on the training origins."""
    info = series_info(data)
    info_pt = dict(info, floor=np.zeros(len(info["keys"])))  # the point versions have no scale floor
    reg = {s.key: s for s in md.registry(md.BLOCKS)}
    idx = month_index(data)
    surveys = {"cleveland": md.fetch_fred("EXPINF1YR").reindex(idx).values,
               "michigan": md.fetch_fred("MICH").reindex(idx).values}
    names, dM, Y = data["names"], data["dM"], data["Y"]
    cpi12 = names.index("us_cpi@12")
    folds = []
    for j in range(mn.FOLDS):
        train, test, last = fold_window(data, j)
        st = Stats(data, last)
        d = design(data, st, last)
        t, y = data["t"][test], Y[test]
        out = {"fold": j, "test_dates": [f"{dd:%Y-%m}" for dd in data["dates"][test]], "names": names, "crps": {}}
        for name, use_oil in (("ar", False), ("ar_oil", True)):
            S = simulate(point_post(d, info, use_oil, DRAWS), st, info_pt, data, t, data["OIL"][test][None],
                         np.random.default_rng(200 + j))
            out["crps"][name] = np.where(np.isfinite(y), crps_samples(S, np.nan_to_num(y)), np.nan).tolist()

        def gauss(f_train, f_test, col):
            sd = np.nanstd(Y[train, col] - f_train)
            return np.where(np.isfinite(y[:, col]) & np.isfinite(f_test), gaussian_crps(f_test, sd, y[:, col]), np.nan)

        rw = np.full(y.shape, np.nan)
        for kk, key in enumerate(info["keys"]):
            if reg[key].target != "inflation":
                continue
            p = reg[key].lag
            pace = lambda tt: np.array([np.nansum(dM[i - p - 11:i - p + 1, kk]) for i in tt])  # noqa: E731
            for hi, h in enumerate(mn.HORIZONS):
                col = kk * len(mn.HORIZONS) + hi
                rw[:, col] = gauss(pace(data["t"][train]) * h / 12, pace(t) * h / 12, col)
        out["crps"]["rw"] = rw.tolist()
        for name, s in surveys.items():  # annual % rate, known at the end of the origin month
            c = np.full(y.shape, np.nan)
            c[:, cpi12] = gauss(100 * np.log1p(s[data["t"][train]] / 100), 100 * np.log1p(s[t] / 100), cpi12)
            out["crps"][name] = c.tolist()
        folds.append(out)
        print(f"benchmarks fold {j} done", flush=True)
    return {"folds": folds, "sources": {"cleveland": "FRED EXPINF1YR", "michigan": "FRED MICH"}}


# --- report ----------------------------------------------------------------------------------

def load(name: str) -> dict | None:
    p = RUNS / name
    return json.loads(p.read_text()) if p.exists() else None


def converged(d: dict) -> bool:
    return d["max_r_hat"] <= 1.05 and d["min_ess"] >= 100


def nw_t(d: np.ndarray, lags: int = 12) -> float:
    """Diebold-Mariano t: mean of the loss differential over its Newey-West error (12 lags, for the
    overlap of 12-month targets)."""
    d = d[np.isfinite(d)]
    e = d - d.mean()
    v = e @ e / len(d)
    for k in range(1, lags + 1):
        v += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / len(d)
    return float(d.mean() / np.sqrt(v / len(d)))


VARIANTS = (("Bayes", "bayes"), ("Bayes+own-vol", "bayes-own"), ("Bayes+CDV", "bayes-cdv"))


def report() -> None:
    folds, failed = [], []
    for j in range(mn.FOLDS):
        b, v = load(f"bayes-fold-{j}.json"), load(f"fold-{j}.json")
        if not (b and v):
            continue
        f = {"fold": j, "v1": v, "anch": load(f"fold-anchored-{j}.json")}
        f |= {name: load(f"{tag}-fold-{j}.json") for name, tag in VARIANTS}
        for name, other in [("v1", v), ("anchored", f["anch"])] + [(n, f[n]) for n, _ in VARIANTS]:
            if other is None:
                continue
            assert other["test_dates"] == b["test_dates"] and other["names"] == b["names"], f"{name} fold {j}: origins or outputs differ"
            assert np.allclose(np.array(other["y"], float), np.array(b["y"], float), equal_nan=True), f"{name} fold {j}: targets differ"
        (folds if converged(b["diagnostics"]) else failed).append(f)
    if not folds:
        raise SystemExit("no converged runs/macro/bayes-fold-*.json yet")
    # a variant gets columns only if it converged on every fold the base model is scored on
    status = {name: [f["fold"] for f in folds if not (f[name] and converged(f[name]["diagnostics"]))] for name, _ in VARIANTS}
    shown = [name for name, _ in VARIANTS if not status[name]]
    bench = load("bayes-benchmarks.json")
    bench = {f["fold"]: f for f in bench["folds"]} if bench else {}
    names, groups = folds[0]["Bayes"]["names"], np.array(folds[0]["Bayes"]["groups"])
    H = np.array([int(n.split("@")[1]) for n in names])

    def stack(get):
        return np.vstack([np.array(get(f), float) for f in folds])

    has_anch = all(f["anch"] for f in folds)
    has_bench = all(f["fold"] in bench for f in folds)
    clim = stack(lambda f: f["v1"]["models"]["climatology"]["crps"])
    scale = np.nanmean(clim, 0)
    C = {}
    for name in shown:
        for mode, label in (("whatif", "what-if"), ("forecast", "forecast")):
            C[f"{name} {label}"] = stack(lambda f: f[name]["modes"][mode]["crps"])
    if has_anch:
        C["anchored nn_mean (what-if)"] = stack(lambda f: f["anch"]["models"]["nn_mean"]["crps"])
    C["v1 nn_mean (what-if)"] = stack(lambda f: f["v1"]["models"]["nn_mean"]["crps"])
    BM = {k: stack(lambda f: bench[f["fold"]]["crps"][k]) for k in ("ar", "ar_oil", "rw", "cleveland", "michigan")} \
        if has_bench else {}
    # the main model: the shown variant with the lowest scaled CRPS over all outputs (what-if)
    main = min(shown, key=lambda n: np.nanmean(np.nanmean(C[f"{n} what-if"], 0) / scale))

    def skill(M, c):
        return 1 - np.nanmean(np.nanmean(M[:, c], 0) / scale[c])

    def diff(M1, M2, c):
        return np.nanmean(np.nanmean((M1[:, c] - M2[:, c]) / scale[c], 1))

    def dm(M1, M2, c):
        return nw_t(np.nanmean((M1[:, c] - M2[:, c]) / scale[c], 1))

    def cols(grp, h="all"):
        return np.where((groups == grp) & ((H == h) if h != "all" else True))[0]

    n_orig = clim.shape[0]
    first, last = folds[0]["Bayes"]["test_dates"][0], folds[-1]["Bayes"]["test_dates"][-1]
    market = folds[0]["Bayes"].get("market")
    out = [
        "# Bayesian oil pass-through (MCMC): results", "",
        f"_Generated by `experiments/macro_bayes.py report` on {datetime.now(UTC).date().isoformat()} from "
        f"{len(folds)} forward-chaining folds ({first}..{last}, {n_orig} forecast origins), the same folds and data "
        "as `notes/macro-nn-results.md` (inputs: `notes/macro-panel.md`, fetched 2026-10-24). The data are real "
        "and revised (not real-time vintages). The only simulated inputs are the forecast mode's oil paths: a block "
        "bootstrap of training months, scaled to the CBOE OVX implied volatility (FRED OVXCLS) and centred on the "
        "WTI futures curve slope (EIA RCLC1-4, to 2024-04)"
        + (f", fetched {market['fetched']}" if market else "") + "._", "",
        "Skill = 1 − CRPS / CRPS of the v1 climatology (training mean and spread), averaged over the outputs in "
        "the group; 0 is no better than climatology. **What-if** forecasts are given the oil path that happened; "
        "**forecast** knows nothing after the origin. Variants: **Bayes** (volatility follows oil), **+own-vol** "
        "(plus each series' own recent volatility), **+CDV** (plus a drifting volatility per target group). Every "
        "column is scored on the same folds and origins.", "",
        f"**Main model: {main}** (the converged variant with the lowest CRPS over all outputs, what-if)."]
    for name, _ in VARIANTS:
        if status[name]:
            out.append(f"**Not shown: {name}** did not converge (or did not run) on fold(s) {status[name]}; see "
                       "Sampler health. Run it with more samples on Iridis (`cluster/iridis/macro_bayes.slurm`).")
    if failed:
        out.append(f"**Excluded:** fold(s) {[f['fold'] for f in failed]} did not converge for the base model.")
    out += ["", "## Skill by horizon", "", "| Target | h | " + " | ".join(C) + " |", "|---|---|" + "---|" * len(C)]
    for grp in GROUPS:
        for h in [*mn.HORIZONS, "all"]:
            b = "**" if h == "all" else ""
            out.append(f"| {grp} | {h} | " + " | ".join(f"{b}{skill(M, cols(grp, h)):+.3f}{b}" for M in C.values()) + " |")

    out += ["", "## Calibration: share of outcomes inside the central 90% interval (target 90%)", ""]
    runs = [(f"{n} {lab}", n, mode) for n in shown for mode, lab in (("whatif", "what-if"), ("forecast", "forecast"))]
    out += ["| Target | " + " | ".join(r[0] for r in runs) + " |", "|---|" + "---|" * len(runs)]
    y_all = stack(lambda f: f["Bayes"]["y"])
    for grp in GROUPS:
        c = cols(grp)
        cells = []
        for _, n, mode in runs:
            lo, hi = stack(lambda f: f[n]["modes"][mode]["q05"]), stack(lambda f: f[n]["modes"][mode]["q95"])
            ok = np.isfinite(y_all[:, c])
            cells.append(f"{np.mean(((y_all[:, c] >= lo[:, c]) & (y_all[:, c] <= hi[:, c]))[ok]):.0%}")
        out.append(f"| {grp} | " + " | ".join(cells) + " |")

    out += ["", "## Are the differences real? Diebold–Mariano tests", "",
            "Mean difference in climatology-scaled CRPS over all horizons (negative: the first model is better), "
            "with its Newey–West t-statistic (12 lags, for the overlapping 12-month targets). |t| > 2 is "
            "roughly significant at 5%.", "",
            "| Comparison | " + " | ".join(GROUPS) + " |", "|---|" + "---|" * len(GROUPS)]
    pairs = [(f"{main} what-if vs anchored nn_mean", C[f"{main} what-if"], C.get("anchored nn_mean (what-if)")),
             (f"{main} forecast vs v1 climatology", C[f"{main} forecast"], clim)]
    pairs += [(f"{n} what-if vs Bayes what-if", C[f"{n} what-if"], C["Bayes what-if"]) for n in shown if n != "Bayes"]
    for label, M1, M2 in pairs:
        if M2 is None:
            continue
        out.append(f"| {label} | " + " | ".join(f"{diff(M1, M2, cols(g)):+.3f} (t {dm(M1, M2, cols(g)):+.1f})" for g in GROUPS) + " |")

    if BM:
        fc = C[f"{main} forecast"]
        cpi = np.array([names.index("us_cpi@12")])
        out += ["", "## Against standard inflation benchmarks (forecast mode: nothing after the origin)", "",
                "Point benchmarks get a Gaussian band with the sd of their own training errors. The surveys are "
                "real-time; our model is scored on revised data, which flatters it slightly (BLS revises seasonally "
                "adjusted CPI only through its seasonal factors). Survey sources: FRED EXPINF1YR (Cleveland Fed) "
                "and MICH (University of Michigan).", "",
                f"| Target | Benchmark | Its skill | {main} forecast skill | {main} minus benchmark (t) |",
                "|---|---|---|---|---|"]
        rows = [("inflation, all horizons", cols("inflation"), "rw", "last 12-month pace carries on"),
                ("inflation, 12 months", cols("inflation", 12), "rw", "last 12-month pace carries on"),
                ("US CPI, 12 months", cpi, "rw", "last 12-month pace carries on"),
                ("US CPI, 12 months", cpi, "cleveland", "Cleveland Fed 1-year expected inflation"),
                ("US CPI, 12 months", cpi, "michigan", "Michigan 1-year expectations")]
        for label, c, k, desc in rows:
            out.append(f"| {label} | {desc} | {skill(BM[k], c):+.3f} | {skill(fc, c):+.3f} | "
                       f"{diff(fc, BM[k], c):+.3f} ({dm(fc, BM[k], c):+.1f}) |")
        out += ["", "## Where the skill comes from (what-if, all horizons)", "",
                "Least-squares versions of the same mean equation, simulated with the same code.", "",
                "| Target | Momentum only | + oil lags (least squares) | " + " | ".join(shown) + " |",
                "|---|---|---|" + "---|" * len(shown)]
        for grp in GROUPS:
            c = cols(grp)
            row = [skill(BM["ar"], c), skill(BM["ar_oil"], c)] + [skill(C[f"{n} what-if"], c) for n in shown]
            out.append(f"| {grp} | " + " | ".join(f"{s:+.3f}" for s in row) + " |")

    # the 2026 closure: the last fold's origins whose 12-month targets fall in it
    lf = folds[-1]
    if lf["fold"] == mn.FOLDS - 1:
        b, r = lf["Bayes"], lf[main]
        out += ["", f"## The 2026 Hormuz closure (12 months ahead, last fold; {main})", "",
                "In each series' units: 100 × log change (≈ % for small moves).", "",
                "| Origin | Output | Actual | What-if (90%) | Forecast (90%) | anchored nn_mean | v1 nn_mean |",
                "|---|---|---|---|---|---|---|"]
        for t in ("2025-03", "2025-06", "2025-09"):
            if t not in b["test_dates"]:
                continue
            i = b["test_dates"].index(t)
            for nm in ("us_cpi@12", "uk_cpi@12", "ea_cpi@12", "ind_gasdesw@12", "ind_djfuelusgulf@12"):
                k = names.index(nm)
                y = b["y"][i][k]
                cell = lambda m: f"{r['modes'][m]['mu'][i][k]:+.1f} ({r['modes'][m]['q05'][i][k]:+.1f}..{r['modes'][m]['q95'][i][k]:+.1f})"  # noqa: E731
                anch = f"{lf['anch']['models']['nn_mean']['mu'][i][k]:+.1f}" if lf["anch"] else "-"
                out.append(f"| {t} | {nm} | {'n/a' if y is None or y != y else f'{y:+.1f}'} | {cell('whatif')} | "
                           f"{cell('forecast')} | {anch} | {lf['v1']['models']['nn_mean']['mu'][i][k]:+.1f} |")

    out += ["", "## Sampler health", "",
            "Converged = max R-hat ≤ 1.05 and min ESS ≥ 100 over every sampled site, hyperparameters included.", "",
            "| Fold | Model | Converged | Seconds | Divergences | Max R-hat | Min ESS | Tree-depth hits |",
            "|---|---|---|---|---|---|---|---|"]
    fins = {name: load(f"{tag}-final.json") for name, tag in VARIANTS}
    for f in sorted(folds + failed, key=lambda f: f["fold"]):
        for name, _ in VARIANTS:
            if f[name]:
                d = f[name]["diagnostics"]
                out.append(f"| {f['fold']} | {name} | {'yes' if converged(d) else '**no**'} | {d['seconds']} | {d['divergences']} | "
                           f"{d['max_r_hat']} | {d['min_ess']} | {d['tree_depth_hits']} |")
    for name, fin in fins.items():
        if fin:
            d = fin["diagnostics"]
            out.append(f"| all data | {name} | {'yes' if converged(d) else '**no**'} | {d['seconds']} | {d['divergences']} | "
                       f"{d['max_r_hat']} | {d['min_ess']} | {d['tree_depth_hits']} |")

    fin = fins[main] if fins.get(main) and converged(fins[main]["diagnostics"]) else fins["Bayes"]
    if fin:
        write_responses(fin)
        keys, p = fin["keys"], fin["params"]
        r_up, r_dn = fin["responses"]["up10"], fin["responses"]["down10"]
        out += ["", f"## Posterior response to a one-off ±10% Brent move (fit on all data; {fin['diagnostics']['vol']} volatility)", "",
                "Change after 3, 12 and 36 months, in the target's units (% of the price level; pp for rates and "
                "unemployment). Posterior mean and 90% interval of the **average** effect: parameter uncertainty "
                "only, not the month-to-month noise around it. 36 months is a scenario: the folds test 12 months "
                "at most. The table is also `notes/macro-bayes-responses.csv`.", "",
                "| Series | +10%, 3 m | +10%, 12 m | +10%, 36 m (scenario) | −10%, 12 m | P(effect > 0), +10% | asymmetry α | oil-vol φ |",
                "|---|---|---|---|---|---|---|---|"]
        for k, key in enumerate(keys):
            c = lambda r, m: f"{r['mean'][k][m]:+.2f} ({r['q05'][k][m]:+.2f}..{r['q95'][k][m]:+.2f})"  # noqa: E731
            out.append(f"| {key} | {c(r_up, 2)} | {c(r_up, 11)} | {c(r_up, SCENARIO - 1)} | {c(r_dn, 11)} | "
                       f"{r_up['p_positive'][k][11]:.2f} | "
                       f"{p['alpha']['mean'][k]:+.2f} ({p['alpha']['q05'][k]:+.2f}..{p['alpha']['q95'][k]:+.2f}) | "
                       f"{p['phi']['mean'][k]:+.2f} |")
    (NOTES / "macro-bayes-results.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {NOTES / 'macro-bayes-results.md'}")


def write_responses(fin: dict) -> None:
    """notes/macro-bayes-responses.csv, the interface for the what-if (World view, household chain):
    one row per series x shock x month ahead."""
    gen = datetime.now(UTC).date().isoformat()
    lines = ["series,group,shock,months_ahead,mean,q05,q95,p_positive,interval,validated,unit,source,fitted_to,generated"]
    for k, key in enumerate(fin["keys"]):
        unit = "pp" if fin["groups"][k] in ("unemployment", "rate") else "% of price level"
        for label, r in (("brent_up_10pct", fin["responses"]["up10"]), ("brent_down_10pct", fin["responses"]["down10"])):
            for m in range(len(r["mean"][k])):
                tested = "yes" if m < mn.OIL_AHEAD else "no (scenario beyond the tested 12 months)"
                lines.append(f"{key},{fin['groups'][k]},{label},{m + 1},{r['mean'][k][m]:.4f},{r['q05'][k][m]:.4f},"
                             f"{r['q95'][k][m]:.4f},{r['p_positive'][k][m]:.3f},"
                             "average effect only (parameter uncertainty; excludes month-to-month noise),"
                             f"{tested},{unit},experiments/macro_bayes.py (FRED/ONS/Eurostat via notes/macro-panel.md),"
                             f"{fin['data_to']},{gen}")
    (NOTES / "macro-bayes-responses.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- entry -----------------------------------------------------------------------------------

def main() -> None:
    global QUICK
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("check", "fold", "final", "benchmarks", "report"))
    p.add_argument("j", nargs="?", type=int, default=0)
    p.add_argument("--vol", choices=("oil", "cdv", "own"), default="oil",
                   help="oil: volatility follows oil only; cdv: plus a drifting volatility per target group; "
                        "own: plus each series' own recent volatility (EWMA of past |changes|)")
    a = p.parse_args()
    if a.cmd == "report":
        return report()
    data = mn.make_dataset(mn.V1_BLOCKS)
    RUNS.mkdir(parents=True, exist_ok=True)
    meta = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "job": os.environ.get("SLURM_JOB_ID")}
    tag = {"oil": "bayes", "cdv": "bayes-cdv", "own": "bayes-own"}[a.vol]
    if a.cmd == "check":
        QUICK = True
        out = run_fold(data, mn.FOLDS - 1, a.vol, market_inputs(data))
        print({m: float(np.nanmean(v["crps"])) for m, v in out["modes"].items()}, out.get("market"))
        return
    if a.cmd == "fold":
        out, path = run_fold(data, a.j, a.vol, market_inputs(data)) | {"meta": meta}, RUNS / f"{tag}-fold-{a.j}.json"
    elif a.cmd == "final":
        out, path = run_final(data, a.vol) | {"meta": meta}, RUNS / f"{tag}-final.json"
    else:
        out, path = run_benchmarks(data) | {"meta": meta}, RUNS / "bayes-benchmarks.json"
    path.write_text(json.dumps(out))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
