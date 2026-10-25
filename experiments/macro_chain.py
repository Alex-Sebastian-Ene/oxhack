# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scipy>=1.11", "xlrd>=2.0", "openpyxl>=3.1", "torch>=2.2",
#                 "jax>=0.4.30", "numpyro>=0.15"]
# ///
"""The knock-on chain end to end: Brent paths -> every knock-on model -> one ensemble, scored on
the forward-chaining folds of macro_bayes.py.

Members (fixed before scoring):
    bayes_own   macro_bayes.py --vol own (MCMC), the main Bayesian model
    global_lin  macro_global.py, shared one-step network plus a per-series linear term
    global      macro_global.py, the shared network only
    global_tcn  macro_global.py, shared one-step TCN (when macro_global provides it)
    margins     margins.py, the refined-product margin member: Brent path plus a simulated product
                margin, mapped onto the three fuel targets (diesel, jet fuel, refinery PPI); it has
                draws for those targets only. With CHAIN_MARGINS=1 it joins every mixture of two or
                more members as one more equal-weight member on those targets' columns (outputs
                tagged -margins); run it with `fold J margins`
    bayes_regime  bayes_own plus the supply-disruption terms (macro_bayes.REGIME: extra oil
                pass-through and a wider band in disruption months), tested as a replacement for
                bayes_own and not adopted (notes/macro-chain-regime.md); only when named
                (`fold J bayes_regime`, CHAIN_MEMBERS). D after the
                origin: the calendar in whatif, D at the origin carried on in levy and bootstrap,
                set by the flow scenario in the replay (REGIME_LOST points or more)
    bayes_regime_cost  the same terms on the cost group (the ind_* series) only; inflation,
                unemployment and rates as in bayes_own. Post hoc: chosen after seeing the 2026
                replay of bayes_regime, so only later 2026 outcomes test it

Oil modes, the same draws for every member (draw n always uses oil path n, so oil and model
uncertainty travel together):
    whatif      the oil path that happened
    levy        a genuine forecast: GARCH-CGMY daily paths -> monthly means (oil_paths.py)
    bootstrap   a genuine forecast: macro_bayes.oil_paths (block bootstrap, OVX, futures)

The ensemble is a mixture: each draw index goes to one member, in proportion to its weight, so
the pairing with the oil path survives. Weights per target group come from a simplex grid (step
0.25, plus equal weights) and are chosen forward: fold j uses the weights with the lowest CRPS on
folds before j (equal weights for fold 0). Equal weights are reported as the robustness check.

    uv run experiments/macro_chain.py check                 # tiny end-to-end run on the last fold
    uv run experiments/macro_chain.py fold 3 [member ...]   # -> runs/macro/chain-3-<member>.{npz,json}
    uv run experiments/macro_chain.py report                # notes/macro-chain-results.md + weights
    uv run experiments/macro_chain.py replay                # the 2026 closure from 2026-02, scenario fan CSV
    CHAIN_MARGINS=1 uv run experiments/macro_chain.py report    # with the margin member (after `fold J margins`)
    CHAIN_RELEASE=none uv run experiments/macro_chain.py replay # scenarios with no emergency stock release
    uv run experiments/macro_chain.py regime                # bayes_regime against bayes_own: folds and replay
                                                            # (after `fold J bayes_own bayes_regime` and
                                                            # CHAIN_MEMBERS=bayes_own,bayes_regime,global_lin,global CHAIN_TAG=regime replay;
                                                            # the cost-only member: `fold J bayes_regime_cost` and
                                                            # CHAIN_MEMBERS=bayes_regime_cost CHAIN_TAG=regimecost replay)
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import time
from datetime import UTC, datetime

import numpy as np
from scipy import stats

import copula as cp
import macro_bayes as mb
import macro_global as mg
import macro_nn as mn
import macro_xattn as mx
import margins
import oil_paths as op

RUNS, NOTES = mb.RUNS, mb.NOTES
MEMBERS = ("bayes_own", "global_lin", "global", "global_tcn", "xattn")
REGIME_KIND = {"bayes_regime": "all", "bayes_regime_cost": "cost"}  # which series take the disruption terms
OPTIONAL = tuple(REGIME_KIND)  # fitted and reported only when named
RECOMMENDED = ("bayes_own", "global_lin", "global")  # the ensemble the earlier runs chose (docs/chain.md)
REGIME_REC = ("bayes_regime", "global_lin", "global")  # RECOMMENDED with bayes_regime in place of bayes_own
COST_REC = ("bayes_regime_cost", "global_lin", "global")  # and with the cost-only member
MODES = ("whatif", "levy", "bootstrap")
JOINT_MODES = ("whatif", "levy")  # modes scored jointly, with independent and copula shocks
STEP = 0.25
# Iridis runs with more networks per variant: CHAIN_SEEDS=20 CHAIN_TAG=s20 (the first 5 networks are
# the default run's, since seeds are base + 100 * variant + s)
TAG = os.environ.get("CHAIN_TAG", "")
MARGIN = "margins"  # the margin member: fuel targets only (margins.TARGETS)
MARGINS = os.environ.get("CHAIN_MARGINS", "") == "1"  # mix it in on the fuel targets (report, replay)
RELEASE = os.environ.get("CHAIN_RELEASE", "2026")  # emergency stocks in the replay's scenarios (reserves.POLICIES)
SPREAD = np.round(np.arange(0.8, 2.001, 0.05), 2)  # calibration: band widening factors tried
QUICK = False


def stem(j: int, member: str) -> str:
    return f"chain-{j}-{member}" + (f"-{TAG}" if TAG else "")


def suffix() -> str:
    return (f"-{TAG}" if TAG else "") + ("-margins" if MARGINS else "") + (f"-release-{RELEASE}" if RELEASE != "2026" else "")


def available() -> tuple[str, ...]:
    """Members this checkout can fit: global_tcn needs macro_global.fit_nets; xattn is macro_xattn.py."""
    return tuple(m for m in MEMBERS if m != "global_tcn" or "global_tcn" in getattr(mg, "VARIANTS", ()))


def draws() -> int:
    return 50 if QUICK else mb.DRAWS


# --- one fold --------------------------------------------------------------------------------

def oil_modes(data: dict, j: int, st: mb.Stats, last: int, t: np.ndarray, market: dict, prices) -> dict:
    """The three oil inputs [N or 1, origins, 12], reproducible per fold, so members fitted at
    different times see the same draws."""
    idx = mb.month_index(data)
    test = np.searchsorted(data["t"], t)
    return {"whatif": data["OIL"][test][None],
            "levy": op.monthly_paths(prices, idx[t], draws(), np.random.default_rng(900 + j), "cgmy", market["drift"][t]),
            "bootstrap": mb.oil_paths(data, st, last, t, draws(), np.random.default_rng(901 + j), market)}


def fit_nets(data: dict, info: dict, st: mb.Stats, last: int, variant: str, base_seed: int) -> tuple[list, list]:
    """The networks of one variant. Network s gets seed base_seed + 100 * VARIANTS.index(variant) + s,
    as macro_global.fit_nets and run_fold (base_seed = 1000 * fold), so the fold files' networks come back."""
    seeds = 2 if QUICK else int(os.environ.get("CHAIN_SEEDS", mg.SEEDS))
    if hasattr(mg, "fit_nets"):
        return mg.fit_nets(data, info, st, last, variant, seeds, base_seed)
    months, k, x, y = mg.training_rows(mg.features(data, st), last)
    seed0 = base_seed + 100 * list(mg.VARIANTS).index(variant)
    fitted = [mg.train(x, k, y, months, info["floor"], variant == "global_lin", seed=seed0 + s) for s in range(seeds)]
    return [f[0] for f in fitted], [f[1] for f in fitted]


def member_simulator(data: dict, info: dict, st: mb.Stats, last: int, t: np.ndarray, member: str, base_seed: int,
                     bayes_seed: int):
    """Fit one member on months 13..last; return (simulate(future, rng, regime=None) -> [N, origins, outputs],
    extra info). regime: D in the 12 months after each origin [origins, 12], used by bayes_regime only."""
    if member in ("bayes_own", *REGIME_KIND):  # the same seed: without a disruption in training they are one fit
        post, st_b, info_b, diag = mb.fit(data, last, seed=bayes_seed, vol="own", regime=REGIME_KIND.get(member))
        return (lambda fut, rng, regime=None: mb.simulate(post, st_b, info_b, data, t, fut, rng, regime=regime)), \
            {"diagnostics": diag} | ({"kappa": quantiles(post["kappa"]), "zeta": quantiles(post["zeta"])} if "kappa" in post else {})
    if member == "xattn":
        nets, training, state = mx.fit_xattn(data, info, st, last, 2 if QUICK else int(os.environ.get("CHAIN_SEEDS", mx.SEEDS)),
                                             base_seed)
        return (lambda fut, rng, regime=None: mx.simulate(nets, state, st, info, data, t, fut, rng, n=draws())), \
            {"training": training, "context": state["ctx"]["codes"], "context_fetched": state["ctx"]["fetched"]}
    nets, training = fit_nets(data, info, st, last, member, base_seed)
    return (lambda fut, rng, regime=None: mg.simulate(nets, st, info, data, t, fut, rng, n=draws())), {"training": training}


def quantiles(x: np.ndarray) -> dict:
    """Posterior mean and 90% interval per series of draws x [N, K]."""
    return {"mean": x.mean(0).tolist(), "q05": np.quantile(x, 0.05, 0).tolist(), "q95": np.quantile(x, 0.95, 0).tolist()}


def mode_regime(data: dict, t: np.ndarray, mode: str) -> np.ndarray:
    """D after each origin for an oil mode: the what-if is told what happened (the calendar); a
    forecast carries D at the origin on."""
    return mb.regime_future(data, t, known=mode == "whatif")


def run_member(data: dict, j: int, member: str, market: dict, prices) -> tuple[dict, dict]:
    """Samples [N, origins, outputs] per oil mode for one member on fold j, and its summary. Every
    mode is simulated twice from the same seed: with independent shocks (mode) and with shocks
    correlated across the series by the fold's t-copula (mode + "_cop")."""
    _, test, last = mb.fold_window(data, j)
    t, Y = data["t"][test], data["Y"][test]
    st = mb.Stats(data, last)
    info = mb.series_info(data)
    oil = oil_modes(data, j, st, last, t, market, prices)
    cop = cp.fit(data, st, last, info)
    t0 = time.time()
    if member == MARGIN:  # fitted on the same training months; NaN outside the fuel targets
        # no copula variant: its shocks are the margins' own, and the mixtures reuse these draws for both
        cm = margins.ChainMargins(data, last)
        S = {mode: cm.member_draws(t, fut, "whatif" if mode == "whatif" else "forecast", seed=(j, k), n=draws()).astype(np.float32)
             for k, (mode, fut) in enumerate(oil.items())}
        extra = {"margins": cm.describe()}
    else:
        sim, extra = member_simulator(data, info, st, last, t, member, 1000 * j, bayes_seed=j)  # the seeds of run_fold
        S = {}
        for mode, fut in oil.items():
            d = mode_regime(data, t, mode)
            S[mode] = sim(fut, np.random.default_rng(300 + j), regime=d).astype(np.float32)
            S[f"{mode}_cop"] = sim(fut, cp.CopulaRNG(np.random.default_rng(300 + j), cop), regime=d).astype(np.float32)
    summary = {"fold": j, "member": member, "test_dates": [f"{d:%Y-%m}" for d in data["dates"][test]],
               "names": data["names"], "groups": data["groups"], "y": Y.tolist(), "seconds": round(time.time() - t0, 1),
               "copula": {k: v for k, v in cop.items() if k not in ("R", "L")},
               "regime_origins": {mode: int(mode_regime(data, t, mode).any(1).sum()) for mode in oil},
               "modes": {mode: mb.summarise(s.astype(float), Y) for mode, s in S.items()}} | extra
    return S, summary


# --- ensemble --------------------------------------------------------------------------------

def simplex(m: int, step: float = STEP) -> np.ndarray:
    """Weight vectors on the simplex with components in multiples of step, plus equal weights."""
    k = round(1 / step)
    grid = [np.array(c) * step for c in itertools.product(range(k + 1), repeat=m) if sum(c) == k]
    eq = np.full(m, 1 / m)
    if not any(np.allclose(g, eq) for g in grid):
        grid.append(eq)
    return np.array(grid)


def assignment(w: np.ndarray, n: int, order: np.ndarray) -> np.ndarray:
    """Member of each draw index: round(w * n) draws each (largest remainder), in a fixed shuffled
    order, so the same draw keeps its oil path whatever the weights."""
    raw = w * n
    counts = np.floor(raw).astype(int)
    counts[np.argsort(raw - counts)[::-1][:n - counts.sum()]] += 1
    out = np.empty(n, int)
    out[order] = np.repeat(np.arange(len(w)), counts)
    return out


def mixture(S: np.ndarray, w: np.ndarray, order: np.ndarray) -> np.ndarray:
    """S: [members, N, ...] -> [N, ...], draw n from member assignment(w)[n]."""
    a = assignment(w, S.shape[1], order)
    return S[a, np.arange(S.shape[1])]


def with_margins(S: np.ndarray, D: np.ndarray | None, w: np.ndarray, order: np.ndarray, cols: list[int]) -> np.ndarray:
    """mixture(S, w, order), except that on the columns `cols` (the fuel targets) the margin member's
    draws D [N, ...] join as one more equal-weight member: weights (w * m / (m + 1), 1 / (m + 1)) for
    a mixture of m members. A single member is left as it is, and so is everything when D is None."""
    M = mixture(S, w, order)
    m = int((w > 0).sum())
    if D is not None and m > 1:
        share = 1 / (m + 1)
        M[..., cols] = mixture(np.concatenate([S, D[None]]), np.r_[w * (1 - share), share], order)[..., cols]
    return M


def fuel_columns(names: list[str]) -> list[int]:
    """Columns of the targets the margin member covers."""
    return [c for c, nm in enumerate(names) if nm.split("@")[0] in margins.TARGETS]


def forward_choice(score: np.ndarray, fold: int, equal: int) -> int:
    """score: [folds, combos] mean scaled CRPS. Fold j takes the best combination on folds < j."""
    return equal if fold == 0 else int(np.argmin(score[:fold].mean(0)))


# --- report ----------------------------------------------------------------------------------

def empirical_crps(train_y: np.ndarray, y: np.ndarray) -> np.ndarray:
    """CRPS [origins, outputs] of each output's empirical distribution of training-origin outcomes."""
    out = np.full(y.shape, np.nan)
    for c in range(y.shape[1]):
        s, ok = train_y[:, c][np.isfinite(train_y[:, c])], np.isfinite(y[:, c])
        if len(s) and ok.any():
            out[ok, c] = mb.crps_samples(s[:, None], y[ok, c])
    return out


def calibration_factor(inside: np.ndarray, target: float = 0.9) -> float:
    """inside: [factors, cells] whether each earlier outcome falls in the band widened by each
    factor in SPREAD; the factor whose coverage is closest to the target."""
    return float(SPREAD[np.argmin(np.abs(inside.mean(1) - target))])


def report() -> None:
    wanted = os.environ.get("CHAIN_MEMBERS", ",".join(MEMBERS)).split(",")  # e.g. CHAIN_MEMBERS=bayes_own,global_lin,global
    members = [m for m in wanted if all((RUNS / f"{stem(j, m)}.npz").exists() for j in range(mn.FOLDS))]
    if not members:
        raise SystemExit(f"no complete runs/macro/{stem(0, '<member>')}.npz set yet")
    missing = [j for j in range(mn.FOLDS) if not (RUNS / f"{stem(j, MARGIN)}.npz").exists()]
    if MARGINS and missing:
        raise SystemExit(f"CHAIN_MARGINS=1 needs runs/macro/{stem(0, MARGIN)}.npz etc.: run `fold J margins` for folds {missing}")
    W = simplex(len(members))
    equal = int(np.argmin(np.abs(W - 1 / len(members)).sum(1)))
    # leave-one-out: equal weights on every member but one (does each member earn its place?)
    loo = {}
    if len(members) >= 3:
        for i, m in enumerate(members):
            w = np.full(len(members), 1 / (len(members) - 1))
            w[i] = 0.0
            loo[m] = len(W)
            W = np.vstack([W, w])
    named = {}  # fixed ensembles worth naming: the earlier recommendation, and it plus the transformer
    for label, ms in (("rec", RECOMMENDED), ("rec+xattn", (*RECOMMENDED, "xattn"))):
        if all(m in members for m in ms) and len(ms) < len(members):
            named[label] = len(W)
            W = np.vstack([W, [1 / len(ms) if m in ms else 0.0 for m in members]])
    data = mn.make_dataset(mn.V1_BLOCKS)
    folds = []
    for j in range(mn.FOLDS):
        v1 = mb.load(f"fold-{j}.json")
        summ = {m: json.loads((RUNS / f"{stem(j, m)}.json").read_text()) for m in members}
        npz = {m: np.load(RUNS / f"{stem(j, m)}.npz") for m in members}
        keys = [k for k in (*MODES, *(f"{x}_cop" for x in JOINT_MODES)) if all(k in npz[m].files for m in members)]
        S = {mode: np.stack([npz[m][mode] for m in members]) for mode in keys}  # float32, as stored
        ref = summ[members[0]]
        for m in members:
            assert summ[m]["test_dates"] == ref["test_dates"] and summ[m]["names"] == ref["names"], f"fold {j} {m}: origins differ"
        assert v1["test_dates"] == ref["test_dates"], f"fold {j}: v1 origins differ"
        train, test = mn.fold_indices(data["dates"], j)
        y = np.array(ref["y"], float)
        assert np.allclose(data["Y"][test], y, equal_nan=True), f"fold {j}: targets differ from the dataset"
        vol = np.array([np.nanmean(np.abs(data["oil_m"][i - 2:i + 1])) for i in data["t"][test]])  # Brent turmoil at the origin
        D = {mode: np.load(RUNS / f"{stem(j, MARGIN)}.npz")[mode].astype(float) for mode in MODES} if MARGINS else None
        folds.append({"summ": summ, "S": S, "D": D, "y": y, "clim": np.array(v1["models"]["climatology"]["crps"], float),
                      "clim_emp": empirical_crps(data["Y"][train], y), "vol": vol})
    names, groups = folds[0]["summ"][members[0]]["names"], np.array(folds[0]["summ"][members[0]]["groups"])
    fuel = fuel_columns(names)
    H = np.array([int(n.split("@")[1]) for n in names])
    scale = np.nanmean(np.vstack([f["clim"] for f in folds]), 0)
    scale_emp = np.nanmean(np.vstack([f["clim_emp"] for f in folds]), 0)

    def cols(grp, h="all"):
        return np.where((groups == grp) & ((H == h) if h != "all" else True))[0]

    # CRPS and 90% bands of every weight combination, per fold and mode
    combo = {mode: [] for mode in MODES}
    eq_samples = {mode: [] for mode in MODES}  # the equal-weight mixture, for calibration
    for j, f in enumerate(folds):
        order = np.random.default_rng(1234 + j).permutation(f["S"]["whatif"].shape[1])
        y = f["y"]
        for mode in MODES:
            crps, lo, hi = [], [], []
            for k, w in enumerate(W):
                M = with_margins(f["S"][mode], f["D"][mode] if MARGINS else None, w, order, fuel)
                crps.append(np.where(np.isfinite(y), mb.crps_samples(M, np.nan_to_num(y)), np.nan))
                lo.append(np.quantile(M, 0.05, 0))
                hi.append(np.quantile(M, 0.95, 0))
                if k == equal:
                    eq_samples[mode].append(M)
            combo[mode].append({"crps": np.array(crps), "lo": np.array(lo), "hi": np.array(hi)})
        print(f"report: fold {j} combinations scored", flush=True)

    # Forward conformal calibration of the equal-weight mixture: per group, fold j widens (or narrows)
    # every draw's distance from the median by the factor that put 90% of earlier folds' outcomes
    # inside the band (factor 1 for fold 0). `const`: one factor; `vol`: one factor for calm and one
    # for turbulent origins (Brent's mean |monthly change| over the last 3 months above the median of
    # earlier folds' origins), since the bands were too wide in calm years and too narrow in crises.
    factor = {(var, mode): {g: [] for g in mb.GROUPS} for var in ("const", "vol") for mode in MODES}
    calibrated = {}
    for mode in MODES:
        stats, inside = [], []
        for f, M in zip(folds, eq_samples[mode]):
            med, q05, q95 = np.median(M, 0), np.quantile(M, 0.05, 0), np.quantile(M, 0.95, 0)
            stats.append((med, q05, q95))
            inside.append(np.array([(f["y"] >= med + s * (q05 - med)) & (f["y"] <= med + s * (q95 - med)) for s in SPREAD]))
        for var in ("const", "vol"):
            parts = {k: [] for k in ("crps", "lo", "hi")}
            for j, (f, M) in enumerate(zip(folds, eq_samples[mode])):
                (med, q05, q95), y = stats[j], f["y"]
                cut = np.median(np.concatenate([folds[i]["vol"] for i in range(j)])) if j and var == "vol" else np.inf
                hot = f["vol"] > cut
                crps, lo, hi = (np.full(y.shape, np.nan) for _ in range(3))
                for g in mb.GROUPS:
                    c = cols(g)
                    s_reg = {}
                    for r in (False, True):
                        cells = [inside[i][:, (folds[i]["vol"] > cut) == r][:, :, c][:, np.isfinite(folds[i]["y"][(folds[i]["vol"] > cut) == r][:, c])]
                                 for i in range(j)]
                        cells = np.concatenate(cells, 1) if cells else np.zeros((len(SPREAD), 0))
                        s_reg[r] = calibration_factor(cells) if cells.shape[1] else 1.0
                    factor[(var, mode)][g].append(s_reg[False] if var == "const" else (s_reg[False], s_reg[True]))
                    s = np.where(hot, s_reg[True], s_reg[False])[:, None]  # [origins, 1]
                    Ms = med[:, c] + s * (M[:, :, c] - med[:, c])
                    crps[:, c] = np.where(np.isfinite(y[:, c]), mb.crps_samples(Ms, np.nan_to_num(y[:, c])), np.nan)
                    lo[:, c], hi[:, c] = med[:, c] + s * (q05[:, c] - med[:, c]), med[:, c] + s * (q95[:, c] - med[:, c])
                for k, v in (("crps", crps), ("lo", lo), ("hi", hi)):
                    parts[k].append(v)
            calibrated[(var, mode)] = {k: np.vstack(v) for k, v in parts.items()}

    chosen = {mode: {} for mode in MODES}  # mode -> group -> [fold] combination index
    for mode in MODES:
        for grp in mb.GROUPS:
            c = cols(grp)
            score = np.array([[np.nanmean(combo[mode][j]["crps"][k][:, c] / scale[c]) for k in range(len(W))]
                              for j in range(len(folds))])
            chosen[mode][grp] = [forward_choice(score, j, equal) for j in range(len(folds))]

    def assemble(mode, pick):
        """[origins, outputs] CRPS / lo / hi with combination pick(group, fold) per group."""
        out = {k: [] for k in ("crps", "lo", "hi")}
        for j in range(len(folds)):
            parts = {k: np.full_like(combo[mode][j]["crps"][0], np.nan) for k in out}
            for grp in mb.GROUPS:
                c = cols(grp)
                for k in out:
                    parts[k][:, c] = combo[mode][j][k][pick(grp, j)][:, c]
            for k in out:
                out[k].append(parts[k])
        return {k: np.vstack(v) for k, v in out.items()}

    rows = {}
    for mode in MODES:
        for i, m in enumerate(members):
            single = int(np.argmax(W[:, i]))  # weight 1 on member i
            rows[(mode, m)] = assemble(mode, lambda g, j, s=single: s)
        rows[(mode, "equal")] = assemble(mode, lambda g, j: equal)
        rows[(mode, "forward")] = assemble(mode, lambda g, j, mode=mode: chosen[mode][g][j])
        rows[(mode, "equal+cal")] = calibrated[("const", mode)]
        rows[(mode, "equal+cal_vol")] = calibrated[("vol", mode)]
        for m, k in loo.items():
            rows[(mode, f"without {m}")] = assemble(mode, lambda g, j, k=k: k)
        for label, k in named.items():
            rows[(mode, label)] = assemble(mode, lambda g, j, k=k: k)
    y_all = np.vstack([f["y"] for f in folds])
    labels = [*members, "equal", *named, "equal+cal", "equal+cal_vol", "forward"]

    # Joint forecasts: energy and variogram scores of all series at each horizon, with independent and
    # with copula-correlated shocks (the same draws otherwise), for each member and the ensembles.
    has_cop = all(f"{m}_cop" in folds[0]["S"] for m in JOINT_MODES)
    joint, jlabels = {}, [*members, "equal", *named]
    if has_cop:
        pick = {m: int(np.argmax(W[:, i])) for i, m in enumerate(members)} | {"equal": equal} | named
        for mode in JOINT_MODES:
            for var in ("", "_cop"):
                for label in jlabels:
                    es, vs = [], []
                    for j, f in enumerate(folds):
                        order = np.random.default_rng(1234 + j).permutation(f["S"]["whatif"].shape[1])
                        M = with_margins(f["S"][mode + var], f["D"][mode] if MARGINS else None, W[pick[label]], order, fuel)
                        e, v = cp.joint_scores(M, f["y"], scale, H, mn.HORIZONS)
                        es.append(e)
                        vs.append(v)
                    joint[(mode, var, label)] = (np.vstack(es), np.vstack(vs))
            print(f"report: joint scores for {mode}", flush=True)

    def skill(M, c, ref=None):
        ref = scale if ref is None else ref
        return 1 - np.nanmean(np.nanmean(M[:, c], 0) / ref[c])

    def diff(A, B, c):
        d = np.nanmean((A[:, c] - B[:, c]) / scale[c], 1)
        return f"{np.nanmean(d):+.3f} (t {mb.nw_t(d):+.1f})"

    first, last = folds[0]["summ"][members[0]]["test_dates"][0], folds[-1]["summ"][members[0]]["test_dates"][-1]
    n_orig = y_all.shape[0]
    _, fetched = op.daily_brent()
    out = ["# The knock-on chain end to end: Lévy oil paths and the model ensemble", "",
           f"_Generated by `experiments/macro_chain.py report` on {datetime.now(UTC).date().isoformat()} from "
           f"{len(folds)} forward-chaining folds ({first}..{last}, {n_orig} forecast origins), the folds and data of "
           "`notes/macro-bayes-results.md` (inputs: `notes/macro-panel.md`; daily Brent FRED DCOILBRENTEU fetched "
           f"{fetched}). Outcomes are real and revised (not real-time vintages). Simulated: the oil paths of the two "
           "forecast modes, and every model's draws._", "",
           "Skill = 1 − CRPS / CRPS of the v1 climatology, averaged over the outputs in the group; 0 is no better than "
           "climatology. Modes: **whatif** is given the oil path that happened; **levy** and **bootstrap** know "
           "nothing after the origin, with oil paths from GARCH-CGMY (`oil_paths.py`) or the block bootstrap. "
           f"Members: {', '.join(f'`{m}`' for m in members)}. **equal**: equal-weight mixture; **forward**: per "
           "group, the weights (simplex grid, step 0.25) with the lowest CRPS on earlier folds (equal for fold 0)."
           + (" **With the margin member** (`experiments/margins.py`, `runs/macro/chain-J-margins.npz`): every mixture "
              "of two or more members takes it as one more equal-weight member on the three fuel targets' columns "
              "(diesel, jet fuel, refinery PPI; cost group); single-member columns are the members alone."
              if MARGINS else ""), ""]
    for mode in MODES:
        out += [f"## {mode}: skill by horizon", "", "| Target | h | " + " | ".join(labels) + " |",
                "|---|---|" + "---|" * len(labels)]
        for grp in mb.GROUPS:
            for h in [*mn.HORIZONS, "all"]:
                b = "**" if h == "all" else ""
                out.append(f"| {grp} | {h} | " + " | ".join(f"{b}{skill(rows[(mode, m)]['crps'], cols(grp, h)):+.3f}{b}"
                                                          for m in labels) + " |")
        out += ["", f"**{mode}: share inside the central 90% interval** (target 90%)", "",
                "| Target | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
        for grp in mb.GROUPS:
            c = cols(grp)
            ok = np.isfinite(y_all[:, c])
            out.append(f"| {grp} | " + " | ".join(
                f"{np.mean(((y_all[:, c] >= rows[(mode, m)]['lo'][:, c]) & (y_all[:, c] <= rows[(mode, m)]['hi'][:, c]))[ok]):.0%}"
                for m in labels) + " |")
        out += ["", f"**{mode}: ensembles against each member** (scaled CRPS difference, Newey–West t; "
                "negative: the ensemble is better)", "", "| Comparison | " + " | ".join(mb.GROUPS) + " |",
                "|---|" + "---|" * len(mb.GROUPS)]
        pairs = [("equal", members), ("equal+cal", ["equal"]), ("equal+cal_vol", ["equal"]), ("forward", [*members, "equal"])]
        pairs += [("rec", ["equal"])] * ("rec" in named) + [("rec+xattn", ["rec", "equal"])] * ("rec+xattn" in named)
        for e, others in pairs:
            for m in others:
                out.append(f"| {e} vs {m} | " + " | ".join(diff(rows[(mode, e)]['crps'], rows[(mode, m)]['crps'], cols(g))
                                                         for g in mb.GROUPS) + " |")
        out.append("")
    if loo:
        out += ["## Does each member earn its place?", "",
                "The equal-weight mixture of all members against the equal-weight mixture without one of them: "
                "scaled CRPS difference (all minus without), Newey–West t. Negative: the member helps.", "",
                "| Mode | Member left out | " + " | ".join(mb.GROUPS) + " |", "|---|---|" + "---|" * len(mb.GROUPS)]
        for mode in ("whatif", "levy"):
            for m in loo:
                out.append(f"| {mode} | {m} | " + " | ".join(diff(rows[(mode, 'equal')]['crps'], rows[(mode, f'without {m}')]['crps'], cols(g))
                                                           for g in mb.GROUPS) + " |")
        out += ["", "Skill of each leave-one-out mixture (all horizons; the full mixture is the `equal` column above):", "",
                "| Mode | Mixture | " + " | ".join(mb.GROUPS) + " |", "|---|---|" + "---|" * len(mb.GROUPS)]
        for mode in ("whatif", "levy"):
            for m in loo:
                out.append(f"| {mode} | without {m} | " + " | ".join(f"{skill(rows[(mode, f'without {m}')]['crps'], cols(g)):+.3f}"
                                                                    for g in mb.GROUPS) + " |")
        out.append("")
    if has_cop:
        cops = [f["summ"][members[0]]["copula"] for f in folds]
        out += ["## Joint forecasts: shocks correlated across the series (t-copula)", "",
                "The same draws with independent shocks and with shocks correlated across the 22 series by each fold's "
                "t-copula (`copula.py`: rank normal scores of the training months' one-step residuals, correlation "
                f"shrunk {cp.SHRINK:.0%} towards the identity, tail index by maximum likelihood). Each series' own "
                "distribution is unchanged; only the dependence changes. Scores: the energy score (ES) and the "
                "variogram score (VS, order 0.5) of all series at each horizon, every output divided by its "
                "climatology CRPS; mean over origins and horizons; lower is better. Δ: copula minus independent, with "
                "the Newey–West t of the per-origin difference (negative: the copula is better).", "",
                "Copula per fold (tail index ν; mean and largest absolute correlation; months with every series "
                "observed): " + "; ".join(f"fold {j} ν {c['nu']:g}, {c['mean_abs_corr']:.2f} / {c['max_corr']:.2f}, "
                                         f"{c['complete_months']}" for j, c in enumerate(cops)) + ".", "",
                "| Mode | Model | ES independent | ES copula | Δ ES (t) | VS independent | VS copula | Δ VS (t) |",
                "|---|---|---|---|---|---|---|---|"]
        for mode in JOINT_MODES:
            for label in jlabels:
                (ei, vi), (ec, vc) = joint[(mode, "", label)], joint[(mode, "_cop", label)]
                de, dv = np.nanmean(ec - ei, 1), np.nanmean(vc - vi, 1)
                out.append(f"| {mode} | {label} | {np.nanmean(ei):.3f} | {np.nanmean(ec):.3f} | {np.nanmean(de):+.3f} "
                           f"(t {mb.nw_t(de):+.1f}) | {np.nanmean(vi):.2f} | {np.nanmean(vc):.2f} | "
                           f"{np.nanmean(dv):+.2f} (t {mb.nw_t(dv):+.1f}) |")
        if "rec+xattn" in named:
            out += ["", "**Does the transformer help the joint forecast?** `rec+xattn` minus `rec`, copula shocks: "
                    + "; ".join(f"{mode} ES {np.nanmean(np.nanmean(joint[(mode, '_cop', 'rec+xattn')][0] - joint[(mode, '_cop', 'rec')][0], 1)):+.3f} "
                                f"(t {mb.nw_t(np.nanmean(joint[(mode, '_cop', 'rec+xattn')][0] - joint[(mode, '_cop', 'rec')][0], 1)):+.1f}), "
                                f"VS {np.nanmean(np.nanmean(joint[(mode, '_cop', 'rec+xattn')][1] - joint[(mode, '_cop', 'rec')][1], 1)):+.2f} "
                                f"(t {mb.nw_t(np.nanmean(joint[(mode, '_cop', 'rec+xattn')][1] - joint[(mode, '_cop', 'rec')][1], 1)):+.1f})"
                                for mode in JOINT_MODES) + "."]
        out.append("")
    out += ["## Against a stricter yardstick", "",
            "Skill against the *empirical* distribution of each output's h-month changes over **all** training "
            "origins of the fold, the yardstick `notes/verification.md` recommends. The v1 climatology above is "
            "Gaussian and fitted on the first 54–70% of the training origins only.", "",
            "| Mode | Target | " + " | ".join(labels) + " |", "|---|---|" + "---|" * len(labels)]
    for mode in ("whatif", "levy"):
        for grp in mb.GROUPS:
            out.append(f"| {mode} | {grp} | " + " | ".join(f"{skill(rows[(mode, m)]['crps'], cols(grp), scale_emp):+.3f}"
                                                         for m in labels) + " |")
    out += ["", "## Calibration factors", "",
            "Each fold scales every draw's distance from the median by the factor that put 90% of the earlier "
            "folds' outcomes inside the band (1 for fold 0; grid 0.8–2.0). `equal+cal`: one factor per group; "
            "`equal+cal_vol`: calm / turbulent origins (Brent's mean absolute monthly change over the last 3 months "
            "above the median of earlier folds' origins).", "",
            "| Variant | Mode | Target | " + " | ".join(f"fold {j}" for j in range(len(folds))) + " |",
            "|---|---|---|" + "---|" * len(folds)]
    for var, label in (("const", "equal+cal"), ("vol", "equal+cal_vol")):
        for mode in ("whatif", "levy"):
            for grp in mb.GROUPS:
                cells = [f"{s:.2f}" if var == "const" else f"{s[0]:.2f} / {s[1]:.2f}" for s in factor[(var, mode)][grp]]
                out.append(f"| {label} | {mode} | {grp} | " + " | ".join(cells) + " |")
    out += ["", "## Lévy against bootstrap oil paths (forecast modes)", "",
            "Scaled CRPS difference, levy minus bootstrap, with its Newey–West t (negative: the Lévy paths give the "
            "better knock-on forecast).", "", "| Model | " + " | ".join(mb.GROUPS) + " |", "|---|" + "---|" * len(mb.GROUPS)]
    for m in labels:
        out.append(f"| {m} | " + " | ".join(diff(rows[('levy', m)]['crps'], rows[('bootstrap', m)]['crps'], cols(g))
                                           for g in mb.GROUPS) + " |")
    out += ["", "## Weights chosen by the forward ensemble", "",
            f"Weights on ({', '.join(members)}) per fold; fold 0 is equal by construction.", "",
            "| Mode | Target | " + " | ".join(f"fold {j}" for j in range(len(folds))) + " |",
            "|---|---|" + "---|" * len(folds)]
    for mode in ("whatif", "levy"):
        for grp in mb.GROUPS:
            out.append(f"| {mode} | {grp} | " + " | ".join("/".join(f"{x:.2f}".rstrip("0").rstrip(".") or "0" for x in W[k])
                                                          for k in chosen[mode][grp]) + " |")
    out += ["", "## Do the members reproduce their own runs?", "",
            "What-if skill of each member refitted here against its earlier file (same folds, seeds and settings; "
            "only the simulation noise differs).", "",
            "| Member | Earlier file | " + " | ".join(mb.GROUPS) + " |", "|---|---|" + "---|" * len(mb.GROUPS)]
    for m, old_stem, get in (("bayes_own", "bayes-own-fold", lambda d: d["modes"]["whatif"]["crps"]),
                         ("global_lin", "global-fold", lambda d: d["models"]["global_lin"]["crps"]),
                         ("global", "global-fold", lambda d: d["models"]["global"]["crps"])):
        if m not in members or not all(mb.load(f"{old_stem}-{j}.json") for j in range(len(folds))):
            continue
        old = np.vstack([np.array(get(mb.load(f"{old_stem}-{j}.json")), float) for j in range(len(folds))])
        out.append(f"| {m} | `{old_stem}-*.json` | " + " | ".join(
            f"{skill(rows[('whatif', m)]['crps'], cols(g)):+.3f} vs {skill(old, cols(g)):+.3f}" for g in mb.GROUPS) + " |")
    # weights for later use (replay, scenarios): the combination with the lowest CRPS over all folds
    best = {mode: {grp: W[forward_choice(np.array([[np.nanmean(combo[mode][j]["crps"][k][:, cols(grp)] / scale[cols(grp)])
                                                     for k in range(len(W))] for j in range(len(folds))]),
                                         len(folds), equal)].tolist()
                   for grp in mb.GROUPS} for mode in MODES}
    (RUNS / f"chain-weights{suffix()}.json").write_text(json.dumps({"members": members, "weights": best,
                                                         "generated": datetime.now(UTC).isoformat(timespec="seconds")}))
    out += ["", "**Weights for the replay and the scenarios** (lowest CRPS over all 8 folds, on "
            f"({', '.join(members)})): " + "; ".join(f"{mode} " + ", ".join(f"{g} {'/'.join(f'{x:g}' for x in w)}"
                                                                          for g, w in best[mode].items())
                                             for mode in ("whatif", "levy")) + "."]
    bayes = [f["summ"]["bayes_own"]["diagnostics"] for f in folds if "bayes_own" in f["summ"]]
    if bayes:
        out += ["", f"**Sampler health (bayes_own):** max R-hat {max(d['max_r_hat'] for d in bayes)}, min ESS "
                f"{min(d['min_ess'] for d in bayes)}, divergences {sum(d['divergences'] for d in bayes)}, "
                f"{'all folds converged' if all(mb.converged(d) for d in bayes) else 'NOT all folds converged'}."]
    (NOTES / f"macro-chain-results{suffix()}.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {NOTES / f'macro-chain-results{suffix()}.md'}")


# --- the 2026 closure: replay and scenario fan ------------------------------------------------

class PairedRNG:
    """A numpy Generator whose standard_t draws take one uniform each, by inverse CDF, so the stream
    stays in step whatever the df. numpy's own sampler uses a varying number of draws per value, and
    the networks' df moves with their oil inputs, so two flow scenarios fell out of step after the
    first month. With it, draw i of every scenario shares all its random numbers, and the difference
    of two scenarios' draws is the effect of the extra lost flow alone. Every other method passes
    through."""

    def __init__(self, rng: np.random.Generator) -> None:
        self.rng = rng

    def standard_t(self, df, size=None):
        df = np.asarray(df, float)
        shape = df.shape if size is None else np.broadcast_shapes(df.shape, tuple(np.atleast_1d(size)))
        u = np.clip(self.rng.random(shape), 1e-12, 1 - 1e-12)
        return stats.t.ppf(u, np.broadcast_to(df, shape))

    def __getattr__(self, name):
        return getattr(self.rng, name)


def effect(x: np.ndarray, base: np.ndarray) -> tuple[float, float, float, float]:
    """Mean, 5%, 50% and 95% of the scenario's draws minus the no-disruption draws, draw by draw."""
    d = x - base
    return (float(d.mean()), *(float(v) for v in np.quantile(d, [0.05, 0.5, 0.95])))


REPLAY_ORIGIN = "2026-02"  # the last month before the closure (7-day flow share below 50% from 2026-03-04)
LOSTS = (0.0, 25.0, 50.0, 82.0, 100.0)  # points of Hormuz flow lost; 82 is what happened
SHOWN = ("us_cpi", "uk_cpi", "ea_cpi", "us_rate", "ind_gasdesw", "ind_djfuelusgulf", "ind_pcu324110324110",
         "ind_pcu325311325311")


def replay_actual(data: dict, m: int) -> dict:
    """What happened after origin month m: each output's change over its h months, where every one of
    those months is published (else NaN)."""
    actual = {}
    for nm in data["names"]:
        key, h = nm.split("@")
        k, h = data["target_keys"].index(key), int(h)
        seg = data["dM"][m + 1:m + 1 + h, k]
        actual[nm] = float(seg.sum()) if len(seg) == h and np.isfinite(seg).all() else np.nan
    return actual


def replay(origin: str = REPLAY_ORIGIN) -> None:
    """Fit every member on months before the origin, simulate from it with (a) the Brent path that
    happened, (b) GARCH-CGMY paths alone and (c) GARCH-CGMY paths plus the flow scenario, mix them
    with equal weights (on the folds, equal weights beat weights chosen on earlier folds), and set
    the result against what happened."""
    import pandas as pd

    data = mn.make_dataset(mn.V1_BLOCKS)
    market, (prices, fetched) = mb.market_inputs(data), op.daily_brent()
    idx = mb.month_index(data)
    m = int(idx.get_loc(pd.Timestamp(origin)))
    last, t = m - 1, np.array([m])
    st, info = mb.Stats(data, last), mb.series_info(data)
    members = os.environ.get("CHAIN_MEMBERS", ",".join(available())).split(",")  # e.g. CHAIN_MEMBERS=bayes_own,global_lin,global
    assert all(m in available() or m in OPTIONAL for m in members), f"{members}: not all available ({available()})"
    equal = np.full(len(members), 1 / len(members))
    real = data["oil_m"][m + 1:m + 1 + mn.OIL_AHEAD]
    seen = int(np.isfinite(real).sum())
    oil = {"whatif": np.nan_to_num(np.r_[real, np.full(mn.OIL_AHEAD - len(real), np.nan)])[None, None]}
    for lost in LOSTS:
        oil[f"lost {lost:g}"] = op.monthly_paths(prices, idx[t], mb.DRAWS, np.random.default_rng(900), "cgmy",
                                                 market["drift"][t], lost=lost, release=RELEASE)
    cop = cp.fit(data, st, last, info)
    # D after the origin (bayes_regime only): the calendar in the what-if, the flow scenario otherwise
    regime = {"whatif": mb.regime_future(data, t, known=True)} | {f"lost {lost:g}": mb.regime_scenario(data, t, lost) for lost in LOSTS}
    S = {mode: [] for mode in oil}
    S_cop = {mode: [] for mode in ("whatif", f"lost {op.LOST_2026:g}")}
    fits = {}
    for mm in members:
        sim, extra = member_simulator(data, info, st, last, t, mm, 90_000, bayes_seed=99)
        fits[mm] = {k: v for k, v in extra.items() if k in ("diagnostics", "kappa", "zeta")}
        if "diagnostics" in extra:
            print(f"replay {mm}: {extra['diagnostics']}", flush=True)
        for mode, fut in oil.items():
            # the flow scenarios share every random number draw by draw, so their differences are effects
            rng = np.random.default_rng(300)
            S[mode].append(sim(fut, rng if mode == "whatif" else PairedRNG(rng), regime=regime[mode])[:, 0])  # [N, outputs]
            if mode in S_cop:
                S_cop[mode].append(sim(fut, cp.CopulaRNG(np.random.default_rng(300), cop), regime=regime[mode])[:, 0])
    RUNS.mkdir(parents=True, exist_ok=True)
    for i, mm in enumerate(members):  # each member's draws, so other mixtures of them can be scored later
        np.savez_compressed(RUNS / f"replay{suffix()}-{mm}.npz",
                            **{mode.replace(" ", "_"): S[mode][i].astype(np.float32) for mode in S},
                            **{mode.replace(" ", "_") + "_cop": S_cop[mode][i].astype(np.float32) for mode in S_cop})
    names, groups = data["names"], np.array(data["groups"])
    order = np.random.default_rng(1234).permutation(mb.DRAWS)
    cm = margins.ChainMargins(data, last) if MARGINS else None
    ens = {}
    D = {}
    for mode, parts in S.items():
        D[mode] = None
        if cm is not None:  # the margin member from the same oil paths; a scenario adds a crisis scaled lost / 82
            # one seed for every flow scenario, so the margin draws stay paired across them too
            lost = None if mode == "whatif" else float(mode.split()[1])
            D[mode] = cm.member_draws(t, oil[mode], "whatif" if mode == "whatif" else "forecast", lost,
                                      seed=(99, 0 if mode == "whatif" else 1), n=mb.DRAWS)[:, 0]
        ens[mode] = with_margins(np.stack(parts), D[mode], equal, order, fuel_columns(names))  # [N, outputs]
    ens_cop = {mode: with_margins(np.stack(parts), D[mode], equal, order, fuel_columns(names)) for mode, parts in S_cop.items()}
    actual = replay_actual(data, m)

    gen = datetime.now(UTC).date().isoformat()
    lines = [f"# Replaying the 2026 Hormuz closure from {origin}", "",
             f"_Generated by `experiments/macro_chain.py replay` on {gen}. Every model is fitted on months up to "
             f"{idx[last]:%Y-%m} only. Outcomes are real (`notes/macro-panel.md`; daily Brent FRED DCOILBRENTEU "
             f"fetched {fetched}); {seen} months of Brent after the origin are known. Members: {', '.join(members)}, "
             "mixed with equal weights, the best ensemble on the 8 folds (`notes/macro-chain-results.md`). "
             + ("Plus the margin member on the three fuel targets (`experiments/margins.py`: product margins fitted on "
                "the same months, crisis term from the IEA actions before 2026, so 2026 is out of sample for it; "
                "`notes/margins-results.md`). " if MARGINS else "")
             + "Simulated: the oil paths and the model draws._", "",
             "- **what-if (out of sample):** the chain is given the Brent path that happened. This tests the knock-on "
             "layer on an event it never saw.",
             "- **lost 0:** a genuine forecast with GARCH-CGMY oil paths and no scenario: what a forecaster without the "
             "flow link would have said.",
             "- **lost 82:** GARCH-CGMY paths plus the flow scenario of the 82 points lost in 2026. **In sample for "
             "the flow link:** its premium curve (`notes/flow-premium.csv`, each path drawn within the curve's 90% "
             "band) was fitted to this same event; Bab el-Mandeb 2023-24 checks only its sign and the role of "
             "rerouting out of sample (`notes/flow-events.md`). So it shows "
             "how the chain composes, not that the flow link forecasts.", "",
             "Mean and central 90% interval, in each series' units (100 × log change ≈ %, pp for rates). ✓ = the "
             "actual is inside the 90% interval.", "",
             "| Series | h | Actual | What-if | Lost 0 (forecast) | Lost 82 (scenario) |", "|---|---|---|---|---|---|"]
    for key in SHOWN:
        for h in (1, 3, 6):
            nm = f"{key}@{h}"
            c = names.index(nm)
            a = actual[nm]

            def cell(mode, c=c, a=a):
                x = ens[mode][:, c]
                lo, hi = np.quantile(x, [0.05, 0.95])
                mark = "" if not np.isfinite(a) else (" ✓" if lo <= a <= hi else " ✗")
                return f"{x.mean():+.1f} ({lo:+.1f}..{hi:+.1f}){mark}"
            lines.append(f"| {key} | {h} | {'n/a' if not np.isfinite(a) else f'{a:+.1f}'} | {cell('whatif')} | "
                         f"{cell('lost 0')} | {cell('lost 82')} |")
    inside = {mode: [] for mode in ("whatif", "lost 0", "lost 82")}
    for c, nm in enumerate(names):
        if np.isfinite(actual[nm]) and int(nm.split("@")[1]) <= 6:
            for mode in inside:
                lo, hi = np.quantile(ens[mode][:, c], [0.05, 0.95])
                inside[mode].append(lo <= actual[nm] <= hi)
    lines += ["", "**Every series, horizons 1–6 with published outcomes:** share of actuals inside the 90% interval: "
              + ", ".join(f"{mode} {np.mean(v):.0%} of {len(v)}" for mode, v in inside.items()) + "."]
    # the joint forecast of every series, independent against copula shocks (outputs scaled by the
    # sd of their training-origin outcomes, so the series count alike)
    H = np.array([int(nm.split("@")[1]) for nm in names])
    y_rep = np.array([[actual[nm] for nm in names]])
    rows_tr = np.flatnonzero(data["t"] + max(mn.HORIZONS) <= last)
    sd = np.nanstd(data["Y"][rows_tr], 0)
    (RUNS / f"replay{suffix()}.json").write_text(json.dumps({
        "origin": origin, "fitted_to": f"{idx[last]:%Y-%m}", "members": members, "names": names, "groups": groups.tolist(),
        "actual": [actual[nm] if np.isfinite(actual[nm]) else None for nm in names], "train_sd": sd.tolist(),
        "regime": {mode: d[0].tolist() for mode, d in regime.items()}, "fits": fits, "brent_fetched": fetched,
        "generated": datetime.now(UTC).isoformat(timespec="seconds"), "job": os.environ.get("SLURM_JOB_ID")}))
    lines += ["", f"**Joint forecast of all series** (t-copula fitted on months to {idx[last]:%Y-%m}: tail index "
              f"{cop['nu']:g}, mean absolute correlation {cop['mean_abs_corr']:.2f}). Energy / variogram score of every "
              "published series at each horizon, each scaled by its training spread; lower is better.", "",
              "| Run | h | ES independent | ES copula | VS independent | VS copula |", "|---|---|---|---|---|---|"]
    for mode in S_cop:
        ei, vi = cp.joint_scores(ens[mode][:, None], y_rep, sd, H, (1, 3, 6))
        ec, vc = cp.joint_scores(ens_cop[mode][:, None], y_rep, sd, H, (1, 3, 6))
        for hi, h in enumerate((1, 3, 6)):
            lines.append(f"| {mode} | {h} | {ei[0, hi]:.3f} | {ec[0, hi]:.3f} | {vi[0, hi]:.2f} | {vc[0, hi]:.2f} |")
    (NOTES / f"chain-replay-2026{suffix()}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # effect_*: the scenario minus no disruption draw by draw (the scenarios share their random numbers)
    pair = [np.corrcoef(ens["lost 0"][:, c], ens["lost 25"][:, c])[0, 1] for c in range(len(names))]
    print(f"pairing: correlation of lost 0 and lost 25 draws, median {np.nanmedian(pair):.3f}, min {np.nanmin(pair):.3f}",
          flush=True)
    rows = ["series,group,flow_drop_points,months_ahead,mean,q05,q50,q95,effect_mean,effect_q05,effect_q50,effect_q95,"
            "actual,unit,validated,origin,source,fitted_to,generated"]
    for c, nm in enumerate(names):
        key, h = nm.split("@")
        grp = groups[c]
        unit = "pp" if grp in ("unemployment", "rate") else "100 x log change (about %)"
        validated = "yes" if grp in ("inflation", "cost") else "no (no causal oil link; forecast only)"
        for lost in LOSTS:
            x = ens[f"lost {lost:g}"][:, c]
            q05, q50, q95 = np.quantile(x, [0.05, 0.5, 0.95])
            eff = ",".join(f"{v:.4f}" for v in effect(x, ens["lost 0"][:, c]))
            a = actual[nm]
            rows.append(f"{key},{grp},{lost:g},{h},{x.mean():.4f},{q05:.4f},{q50:.4f},{q95:.4f},{eff},"
                        f"{'' if not np.isfinite(a) else f'{a:.4f}'},{unit},{validated},{origin},"
                        "experiments/macro_chain.py replay (oil: GARCH-CGMY + notes/flow-premium.csv premium sampled in its band; "
                        f"models: {'+'.join(members + ([MARGIN] if MARGINS else []))}),{idx[last]:%Y-%m},{gen}")
    (NOTES / f"chain-scenarios{suffix()}.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"wrote {NOTES / f'chain-replay-2026{suffix()}.md'} and {NOTES / f'chain-scenarios{suffix()}.csv'}")


# --- bayes_regime against bayes_own: the keep rule ---------------------------------------------

KEEP_T = 2.0  # a group is worse if candidate minus incumbent has a Newey-West t above this
# What was decided once the results were in (the rule's outcome alone did not settle it)
REGIME_DECISION = ("Not adopted (2026-10-25): the recommended ensemble stays `rec`. The rule's pass is narrow and comes "
                   "from the mixture's spread; inflation, the app's headline, is worse in the scenario run.")
REGIME_COST_DECISION = ("not adopted: `rec` stays recommended until the recheck on 2026 outcomes published after the "
                        "replay (the 12-month horizon).")
REGIME_MODES = ("whatif", "lost_0", "lost_82")  # replay modes scored; lost_82 (D from the scenario) decides


def regime_scores(M: np.ndarray, y: np.ndarray) -> dict:
    """CRPS and the central 90% band of draws M [N, ...] at outcomes y [...]."""
    M = M.astype(float)
    return {"crps": np.where(np.isfinite(y), mb.crps_samples(M, np.nan_to_num(y)), np.nan),
            "lo": np.quantile(M, 0.05, 0), "hi": np.quantile(M, 0.95, 0)}


def regime_models(get, order: np.ndarray, cost: bool = False) -> dict:
    """The models compared, from get(member) -> draws [N, ...]: each Bayesian member alone, and the
    recommended ensemble with each of them (equal weights, the same draw order, so draw n comes from
    the Bayesian member in every ensemble or in none). cost: also the cost-only member and its ensemble."""
    w = np.full(len(RECOMMENDED), 1 / len(RECOMMENDED))
    out = {"bayes_own": get("bayes_own"), "bayes_regime": get("bayes_regime"),
           "rec": mixture(np.stack([get(m) for m in RECOMMENDED]), w, order),
           "rec_regime": mixture(np.stack([get(m) for m in REGIME_REC]), w, order)}
    if cost:
        out |= {"bayes_regime_cost": get("bayes_regime_cost"),
                "rec_regime_cost": mixture(np.stack([get(m) for m in COST_REC]), w, order)}
    return out


def regime_verdict(t_folds: dict, replay: dict) -> tuple[bool, list[str]]:
    """t_folds: (mode, group) -> Newey-West t of rec_regime minus rec on the folds; replay: model ->
    (mean scaled CRPS, coverage) in the deciding replay mode. Kept if no group is worse beyond KEEP_T
    and the replay improves: lower CRPS, coverage no lower."""
    why = [f"{mode} {g}: worse (t {t:+.1f})" for (mode, g), t in t_folds.items() if t > KEEP_T]
    (c_new, v_new), (c_old, v_old) = replay["rec_regime"], replay["rec"]
    if not c_new < c_old:
        why.append(f"replay: CRPS {c_new:.3f} is not below {c_old:.3f}")
    if v_new < v_old:
        why.append(f"replay: coverage {v_new:.0%} is below {v_old:.0%}")
    return not why, why


def regime_report() -> None:
    """notes/macro-chain-regime.md: bayes_regime against bayes_own, alone and inside the recommended
    ensemble, on the 8 folds (runs/macro/chain-J-<member>.npz) and the 2026 replay
    (runs/macro/replay-regime-<member>.npz, from CHAIN_TAG=regime replay with all four members)."""
    need = sorted(set(RECOMMENDED) | set(REGIME_REC))
    missing = [f"{stem(j, m)}.npz" for j in range(mn.FOLDS) for m in need if not (RUNS / f"{stem(j, m)}.npz").exists()]
    missing += [f"replay-regime-{m}.npz" for m in need if not (RUNS / f"replay-regime-{m}.npz").exists()]
    if missing:
        raise SystemExit(f"missing in runs/macro: {', '.join(missing)}")
    # the cost-only member, if its runs are there (folds tagged like the rest; its own replay run, tag regimecost)
    cm = "bayes_regime_cost"
    cost = all((RUNS / f"{stem(j, cm)}.npz").exists() for j in range(mn.FOLDS)) and (RUNS / f"replay-regimecost-{cm}.npz").exists()
    load_as = need + [cm] * cost
    data = mn.make_dataset(mn.V1_BLOCKS)
    clim = [np.array(mb.load(f"fold-{j}.json")["models"]["climatology"]["crps"], float) for j in range(mn.FOLDS)]
    scale = np.nanmean(np.vstack(clim), 0)
    acc, joint, hot, diags, diags_cost, fold_of = {}, {}, {mode: [] for mode in MODES}, [], [], []
    for j in range(mn.FOLDS):
        npz = {m: np.load(RUNS / f"{stem(j, m)}.npz") for m in load_as}
        summ = {m: json.loads((RUNS / f"{stem(j, m)}.json").read_text()) for m in load_as}
        ref = summ["bayes_own"]
        for m in load_as:
            assert summ[m]["test_dates"] == ref["test_dates"] and summ[m]["names"] == ref["names"], f"fold {j} {m}: origins differ"
        _, test = mn.fold_indices(data["dates"], j)
        y, t = np.array(ref["y"], float), data["t"][test]
        assert np.allclose(data["Y"][test], y, equal_nan=True), f"fold {j}: targets differ from the dataset"
        fold_of.append(np.full(len(t), j))
        order = np.random.default_rng(1234 + j).permutation(npz["bayes_own"]["whatif"].shape[0])
        for mode in MODES:
            hot[mode].append(mode_regime(data, t, mode).any(1))
            for name, M in regime_models(lambda m: npz[m][mode], order, cost).items():
                for k, v in regime_scores(M, y).items():
                    acc.setdefault((mode, name), {}).setdefault(k, []).append(v)
        H = np.array([int(n.split("@")[1]) for n in ref["names"]])
        for mode in JOINT_MODES:
            for name, M in regime_models(lambda m: npz[m][f"{mode}_cop"], order, cost).items():
                joint.setdefault((mode, name), []).append(cp.joint_scores(M.astype(float), y, scale, H, mn.HORIZONS)[0])
        diags.append(summ["bayes_regime"]["diagnostics"])
        if cost:
            diags_cost.append(summ[cm]["diagnostics"])
    rows = {k: {kk: np.vstack(vv) for kk, vv in v.items()} for k, v in acc.items()}
    hot = {mode: np.concatenate(v) for mode, v in hot.items()}
    fold_of = np.concatenate(fold_of)
    regime_folds = [j for j, d in enumerate(diags) if d.get("regime")]
    in_regime_folds = np.isin(fold_of, regime_folds)  # elsewhere bayes_regime is bayes_own
    names, groups = ref["names"], np.array(ref["groups"])
    H = np.array([int(n.split("@")[1]) for n in names])
    y_all = np.vstack([np.array(json.loads((RUNS / f"{stem(j, 'bayes_own')}.json").read_text())["y"], float)
                       for j in range(mn.FOLDS)])

    def cols(grp):
        return np.where(groups == grp)[0]

    def per_origin(A, B, c, mask=None):
        d = np.nanmean((A[:, c] - B[:, c]) / scale[c], 1)
        return d if mask is None else d[mask]

    def cell(A, B, c, mask=None):
        d = per_origin(A, B, c, mask)
        if len(d) < 2:
            return "–"
        # the Newey-West error needs many more origins than its 12 lags; below that, the mean and the count
        return f"{np.nanmean(d):+.3f} (t {mb.nw_t(d):+.1f})" if len(d) >= 4 * 12 else f"{np.nanmean(d):+.3f} (n {len(d)}, no t)"

    def skill(M, c):
        return 1 - np.nanmean(np.nanmean(M[:, c], 0) / scale[c])

    def cover(r, c):
        ok = np.isfinite(y_all[:, c])
        return np.mean(((y_all[:, c] >= r["lo"][:, c]) & (y_all[:, c] <= r["hi"][:, c]))[ok])

    t_folds = {(mode, g): mb.nw_t(per_origin(rows[(mode, "rec_regime")]["crps"], rows[(mode, "rec")]["crps"], cols(g)))
               for mode in ("whatif", "levy") for g in mb.GROUPS}

    # the replay. Outcomes come from the current data, so a rerun after a refresh scores the months
    # published since (the draws stay those of the fits to the origin)
    import pandas as pd

    meta = json.loads((RUNS / "replay-regime.json").read_text())
    rep = {m: np.load(RUNS / f"replay-regime-{m}.npz") for m in need}
    assert meta["names"] == names, "replay outputs differ from the folds'"
    meta_cost = {}
    if cost:
        meta_cost = json.loads((RUNS / "replay-regimecost.json").read_text())
        assert (meta_cost["origin"], meta_cost["fitted_to"], meta_cost["names"]) == (meta["origin"], meta["fitted_to"], names), \
            "the cost-only replay was run from another origin or fit"
        rep[cm] = np.load(RUNS / f"replay-regimecost-{cm}.npz")
    m0 = int(mb.month_index(data).get_loc(pd.Timestamp(meta["origin"])))
    got = replay_actual(data, m0)
    actual = np.array([got[nm] for nm in names], float)
    sd = np.array(meta["train_sd"], float)
    pub = np.isfinite(actual) & (H <= 6)
    late = np.isfinite(actual) & (H >= 7)  # published only after the replay's run: the recheck
    order = np.random.default_rng(1234).permutation(rep["bayes_own"]["whatif"].shape[0])  # the replay's own order
    rscore = {}
    for mode in REGIME_MODES:
        for name, M in regime_models(lambda m: rep[m][mode], order, cost).items():
            r = regime_scores(M, actual)
            # also the median's error and the band's width, to tell accuracy from spread
            rscore[(mode, name)] = {"crps": r["crps"] / sd, "inside": (actual >= r["lo"]) & (actual <= r["hi"]),
                                    "mae": np.abs(np.median(M.astype(float), 0) - actual) / sd, "width": (r["hi"] - r["lo"]) / sd}
    deciding = {name: (float(np.mean(rscore[("lost_82", name)]["crps"][pub])), float(np.mean(rscore[("lost_82", name)]["inside"][pub])))
                for name in ("rec", "rec_regime")}
    keep, why = regime_verdict(t_folds, deciding)

    def rgroup(mode, name, g, what="crps"):
        c = np.intersect1d(cols(g), np.flatnonzero(pub))
        return float(np.mean(rscore[(mode, name)][what][c])) if len(c) else np.nan

    # the reviewer's checks (cost-of-living session), reported beside the rule: the lost-82 row improves
    # inflation and costs without losing coverage, and the what-if row agrees in sign
    checks = []
    for g in ("inflation", "cost"):
        d82 = rgroup("lost_82", "rec_regime", g) - rgroup("lost_82", "rec", g)
        dwi = rgroup("whatif", "rec_regime", g) - rgroup("whatif", "rec", g)
        checks.append((f"lost 82, {g}: CRPS rec_regime − rec {d82:+.3f}", d82 < 0))
        checks.append((f"what-if, {g}: {dwi:+.3f}, same sign as lost 82", np.sign(dwi) == np.sign(d82)))
    checks.append((f"lost 82, coverage {deciding['rec_regime'][1]:.0%} against {deciding['rec'][1]:.0%}",
                   deciding["rec_regime"][1] >= deciding["rec"][1]))
    checks_pass = all(ok for _, ok in checks)
    alone = {mode: [float(np.mean(rscore[(mode, m)][w][pub])) for m in ("bayes_own", "bayes_regime", "rec", "rec_regime")
                    for w in ("crps", "inside")] for mode in ("whatif", "lost_82")}

    def mean_at(mode, name, mask, what="crps"):
        return float(np.mean(rscore[(mode, name)][what][mask])) if mask.any() else np.nan

    def cost_section() -> tuple[str, list[str]]:
        """The cost-only variant: its verdict line and its section."""
        t_cost = {(mode, g): mb.nw_t(per_origin(rows[(mode, "rec_regime_cost")]["crps"], rows[(mode, "rec")]["crps"], cols(g)))
                  for mode in ("whatif", "levy") for g in mb.GROUPS}
        keep_c, why_c = regime_verdict(t_cost, {"rec": deciding["rec"], "rec_regime": (mean_at("lost_82", "rec_regime_cost", pub),
                                                                                       mean_at("lost_82", "rec_regime_cost", pub, "inside"))})
        line = ("**Cost-only variant, post hoc (chosen after seeing this replay):** "
                + ("passes the same rule on these numbers" if keep_c else "fails the same rule (" + "; ".join(why_c) + ")")
                + f"; {REGIME_COST_DECISION} {int(late.sum())} replay outcomes after horizon 6 are published so far.")
        on_c = [j for j, d in enumerate(diags_cost) if d.get("regime")]
        o = ["", "## The cost-only variant (post hoc)", "",
             "**Post hoc: chosen after seeing the 2026 replay above.** `bayes_regime_cost` puts κ and ζ on the cost group (the "
             "ind_* series) only; inflation, unemployment and rates are modelled as in bayes_own, so their draws differ from "
             f"bayes_own's only by the Monte Carlo noise of a separate MCMC run (the terms fitted on fold(s) {on_c}). "
             f"`rec_regime_cost` = equal weights on ({', '.join(COST_REC)}). Its replay scores at horizons 1–6 are not a "
             "test, since the variant was picked from them; the test is the outcomes published after the replay was run "
             "(the 12-month horizon, complete from 2027-02).", "", line, ""]
        for mode in MODES:
            o += [f"**Folds, {mode}:** scaled CRPS difference (Newey–West t, or mean and count where too few origins) and "
                  "coverage.", "", "| Target | bayes_regime_cost − bayes_own | rec_regime_cost − rec | fitted folds | "
                  "D = 1 origins | rec cover | rec_regime_cost cover |", "|---|---|---|---|---|---|---|"]
            for g in mb.GROUPS:
                c = cols(g)
                A, B = rows[(mode, "rec_regime_cost")]["crps"], rows[(mode, "rec")]["crps"]
                o.append(f"| {g} | {cell(rows[(mode, cm)]['crps'], rows[(mode, 'bayes_own')]['crps'], c)} | {cell(A, B, c)} | "
                         f"{cell(A, B, c, in_regime_folds)} | {cell(A, B, c, hot[mode] & in_regime_folds)} | "
                         f"{cover(rows[(mode, 'rec')], c):.0%} | {cover(rows[(mode, 'rec_regime_cost')], c):.0%} |")
            o.append("")
        o += ["**Folds, joint forecast** (energy score, copula shocks): " + "; ".join(
            f"{mode} rec {np.nanmean(np.vstack(joint[(mode, 'rec')])):.3f}, rec_regime_cost "
            f"{np.nanmean(np.vstack(joint[(mode, 'rec_regime_cost')])):.3f}" for mode in JOINT_MODES) + ".", "",
              "**The replay**, scored apart on horizons 1–6 (in sample for the choice) and horizon 12 (published after the "
              "run: the recheck). Mean scaled CRPS and coverage.", "",
              "| Mode | h 1–6: rec | h 1–6: rec_regime_cost | rec cover | rec_regime_cost cover | h ≥ 7 published | "
              "h ≥ 7: rec | h ≥ 7: rec_regime_cost |", "|---|---|---|---|---|---|---|---|"]
        for mode in REGIME_MODES:
            f7 = (lambda nm: f"{mean_at(mode, nm, late):.3f}" if late.any() else "–")  # noqa: E731
            o.append(f"| {mode} | {mean_at(mode, 'rec', pub):.3f} | {mean_at(mode, 'rec_regime_cost', pub):.3f} | "
                     f"{mean_at(mode, 'rec', pub, 'inside'):.0%} | {mean_at(mode, 'rec_regime_cost', pub, 'inside'):.0%} | "
                     f"{int(late.sum())} | {f7('rec')} | {f7('rec_regime_cost')} |")
        on_cost = pub & (groups == "cost")

        def change(mode, a, b, what):
            return 100 * (mean_at(mode, b, on_cost, what) / mean_at(mode, a, on_cost, what) - 1)
        o += ["", "**The member alone, and accuracy against spread** (horizons 1–6): scaled CRPS, the median's absolute "
              "error and the 90% band's width (both divided by the training spread), and coverage, over every published "
              "output and over the cost group.", "",
              "| Mode | Model | CRPS | median error | band width | cover | cost CRPS | cost median error | cost band width | "
              "cost cover |", "|---|---|---|---|---|---|---|---|---|---|"]
        for mode in ("whatif", "lost_82"):
            for nm in ("bayes_own", cm, "rec", "rec_regime_cost"):
                o.append(f"| {mode} | {nm} | " + " | ".join(
                    f"{mean_at(mode, nm, mask, w):.0%}" if w == "inside" else f"{mean_at(mode, nm, mask, w):.3f}"
                    for mask in (pub, on_cost) for w in ("crps", "mae", "width", "inside")) + " |")
        o += ["", "On the cost group the member alone puts its median "
              + " and ".join(f"{-change(mode, 'bayes_own', cm, 'mae'):.0f}% closer than bayes_own's ({mode.replace('_', ' ')}; "
                             f"band {change(mode, 'bayes_own', cm, 'width'):+.0f}%)" for mode in ("whatif", "lost_82"))
              + ", so its gain is not only the mixture's. Inside the ensemble the median moves "
              + " and ".join(f"{-change(mode, 'rec', 'rec_regime_cost', 'mae'):.0f}% closer (band "
                             f"{change(mode, 'rec', 'rec_regime_cost', 'width'):+.0f}%)" for mode in ("whatif", "lost_82"))
              + ": there most of the CRPS gain is the wider band."]
        o += ["", "By target group, horizons 1–6:", "",
              "| Mode | Target | rec CRPS | rec_regime_cost CRPS | difference | rec cover | rec_regime_cost cover |",
              "|---|---|---|---|---|---|---|"]
        for mode in ("whatif", "lost_82"):
            for g in mb.GROUPS:
                a, b = rgroup(mode, "rec", g), rgroup(mode, "rec_regime_cost", g)
                o.append(f"| {mode} | {g} | {a:.3f} | {b:.3f} | {b - a:+.3f} | {rgroup(mode, 'rec', g, 'inside'):.0%} | "
                         f"{rgroup(mode, 'rec_regime_cost', g, 'inside'):.0%} |")
        fc, fa = meta_cost.get("fits", {}).get(cm, {}), meta["fits"].get("bayes_regime", {})
        if fc.get("kappa"):
            keys = data["target_keys"]
            o += ["", f"**Cost multipliers, replay fit** (to {meta['fitted_to']}, learned from 2022 only), the cost-only member "
                  "against bayes_regime: 1 + κ and exp(ζ), posterior mean and 90% interval.", "",
                  "| Series | cost-only 1 + κ | cost-only exp(ζ) | bayes_regime 1 + κ | bayes_regime exp(ζ) |", "|---|---|---|---|---|"]

            def pk(f, i):
                return f"{1 + f['kappa']['mean'][i]:.2f} ({1 + f['kappa']['q05'][i]:.2f}..{1 + f['kappa']['q95'][i]:.2f})"

            def pz(f, i):
                return f"{np.exp(f['zeta']['mean'][i]):.2f} ({np.exp(f['zeta']['q05'][i]):.2f}..{np.exp(f['zeta']['q95'][i]):.2f})"
            for i, key in enumerate(keys):
                if groups[names.index(f"{key}@1")] == "cost":
                    o.append(f"| {key} | {pk(fc, i)} | {pz(fc, i)} | {pk(fa, i) if fa.get('kappa') else '–'} | "
                             f"{pz(fa, i) if fa.get('zeta') else '–'} |")
        o += ["", "**Sampler health (bayes_regime_cost):** " + "; ".join(
            f"fold {j} {'on' if d.get('regime') else 'off'} R-hat {d['max_r_hat']} ESS {d['min_ess']} div {d['divergences']}"
            for j, d in enumerate(diags_cost))
              + (f"; replay {'on' if fc['diagnostics'].get('regime') else 'off'} R-hat {fc['diagnostics']['max_r_hat']} "
                 f"ESS {fc['diagnostics']['min_ess']} div {fc['diagnostics']['divergences']}" if fc.get("diagnostics") else "") + "."]
        return line, o

    cost_line, cost_lines = cost_section() if cost else ("", [])

    models = ("bayes_own", "bayes_regime", "rec", "rec_regime")
    gen = datetime.now(UTC).date().isoformat()
    on = [j for j, d in enumerate(diags) if d.get("regime")]
    out = ["# Supply-disruption terms in the chain: bayes_regime against bayes_own", "",
           f"_Generated by `experiments/macro_chain.py regime` on {gen}. Folds: the 8 forward-chaining folds and seeds of "
           "`notes/macro-chain-results.md` (outcomes real and revised, inputs `notes/macro-panel.md`); replay: every model "
           f"fitted on months to {meta['fitted_to']}, simulated from {meta['origin']} (daily Brent fetched "
           f"{meta['brent_fetched']}). Simulated: the oil paths and the model draws._", "",
           "**The terms** (`macro_bayes.py`, from `experiments/cost_of_living.py`): D = 1 in supply-disruption months "
           "(" + "; ".join(f"{a[:7]}..{b[:7]} {why_}" for a, b, why_ in mb.REGIME) + "). Then the oil term is multiplied by "
           "(1 + κ[k]), κ pooled by target group, and the error scale by exp(ζ[k]). A fold whose training months hold no "
           f"disruption fits without them, so there bayes_regime is bayes_own (regime fitted on fold(s) {on}). D after the "
           "origin: the calendar in **whatif** (told what happened), D at the origin carried on in **levy** and "
           f"**bootstrap**, and in the replay scenarios on when at least {mb.REGIME_LOST:g} points of Hormuz flow are lost.", "",
           "**Models:** `bayes_own` and `bayes_regime` alone; `rec` = equal weights on "
           f"({', '.join(RECOMMENDED)}), the recommended ensemble; `rec_regime` = the same with bayes_regime in place of "
           "bayes_own (same draw order).", "",
           f"**Keep rule** (fixed before scoring): no target group worse beyond {KEEP_T:g} Newey–West errors on the folds "
           "(rec_regime minus rec, what-if and levy), and the replay improves in its deciding mode, lost 82 with D from "
           "the scenario: lower mean scaled CRPS and coverage no lower.", "",
           "## Verdict", "",
           ("**Passes the keep rule.** " if keep else "**Fails the keep rule.** ")
           + ("No group is worse on the folds, and the replay improves." if keep else "; ".join(why) + "."), "",
           f"**Decision:** {REGIME_DECISION}", "",
           "**Reviewer's checks** (the cost-of-living session; reported, not part of the rule): "
           + "; ".join(f"{label} {'✓' if ok else '✗'}" for label, ok in checks) + ". "
           + ("They agree with the verdict." if checks_pass == keep else "**They disagree with the verdict.**"), "",
           "**The member alone:** in the replay bayes_regime scores " + "; ".join(
               f"{mode.replace('_', ' ')} {a[2]:.3f} against bayes_own's {a[0]:.3f}" for mode, a in alone.items())
           + ". Inside the ensemble the what-if moves from " + f"{alone['whatif'][4]:.3f} to {alone['whatif'][6]:.3f} with "
           f"coverage {alone['whatif'][5]:.0%} → {alone['whatif'][7]:.0%}: where the member alone is worse, the ensemble's "
           "gain comes from the mixture's wider spread, not a sharper member.", "",
           f"**How much evidence:** only fold(s) {regime_folds} have a disruption in training, so on the other folds "
           "bayes_regime is bayes_own and the fold comparison is a no-harm check; "
           f"{int((hot['whatif'] & in_regime_folds).sum())} what-if origins and "
           f"{int((hot['levy'] & in_regime_folds).sum())} forecast origins there have D = 1 ahead. The replay is one "
           "origin. Both are thin evidence either way: κ and ζ are learned from the 10 months of 2022 alone."]
    if cost_line:
        out += ["", cost_line]
    for mode in MODES:
        out += ["", f"## Folds, {mode}", "",
                f"Origins whose 12 months ahead include D = 1: {int(hot[mode].sum())} of {len(hot[mode])}.", "",
                "| Target | " + " | ".join(f"{m} skill" for m in models) + " | " + " | ".join(f"{m} 90% cover" for m in models) + " |",
                "|---|" + "---|" * (2 * len(models))]
        for g in mb.GROUPS:
            c = cols(g)
            out.append(f"| {g} | " + " | ".join(f"{skill(rows[(mode, m)]['crps'], c):+.3f}" for m in models) + " | "
                       + " | ".join(f"{cover(rows[(mode, m)], c):.0%}" for m in models) + " |")
        out += ["", "Scaled CRPS difference (Newey–West t; negative: the first is better), over all origins, over the "
                f"folds where the terms are fitted ({regime_folds}), and over those folds' origins whose 12 months ahead "
                "include D = 1.", "",
                "| Target | bayes_regime − bayes_own | rec_regime − rec | rec_regime − rec, fitted folds | "
                "rec_regime − rec, D = 1 origins |", "|---|---|---|---|---|"]
        for g in mb.GROUPS:
            c = cols(g)
            A, B = rows[(mode, "rec_regime")]["crps"], rows[(mode, "rec")]["crps"]
            out.append(f"| {g} | {cell(rows[(mode, 'bayes_regime')]['crps'], rows[(mode, 'bayes_own')]['crps'], c)} | "
                       f"{cell(A, B, c)} | {cell(A, B, c, in_regime_folds)} | {cell(A, B, c, hot[mode] & in_regime_folds)} |")
    out += ["", "## Folds, joint forecast (copula shocks)", "",
            "Energy score of all series at each horizon (outputs scaled by their climatology CRPS; lower is better), and "
            "rec_regime minus rec with its Newey–West t.", "", "| Mode | " + " | ".join(models) + " | rec_regime − rec |",
            "|---|" + "---|" * (len(models) + 1)]
    for mode in JOINT_MODES:
        es = {m: np.vstack(joint[(mode, m)]) for m in models}
        d = np.nanmean(es["rec_regime"] - es["rec"], 1)
        out.append(f"| {mode} | " + " | ".join(f"{np.nanmean(es[m]):.3f}" for m in models) + f" | {np.nanmean(d):+.3f} (t {mb.nw_t(d):+.1f}) |")
    out += ["", f"## The 2026 replay from {meta['origin']}", "",
            "Every series at horizons 1–6 with a published outcome "
            f"({int(pub.sum())} outputs): mean CRPS scaled by each output's training spread (lower is better) and the share "
            "of actuals inside the central 90% interval. **whatif**: the Brent path that happened, D from the calendar (it "
            "is told a disruption began in 2026-03). **lost 0**: a forecast with GARCH-CGMY paths and no scenario (D stays "
            "0). **lost 82**: the paths plus the 2026 flow scenario, D from the scenario; the flow link was fitted to this "
            "event, so it is in sample for that link, equally for both ensembles.", "",
            "| Mode | " + " | ".join(f"{m} CRPS" for m in models) + " | " + " | ".join(f"{m} cover" for m in models) + " |",
            "|---|" + "---|" * (2 * len(models))]
    for mode in REGIME_MODES:
        out.append(f"| {mode} | " + " | ".join(f"{np.mean(rscore[(mode, m)]['crps'][pub]):.3f}" for m in models) + " | "
                   + " | ".join(f"{np.mean(rscore[(mode, m)]['inside'][pub]):.0%}" for m in models) + " |")
    out += ["", "By target group (scaled CRPS and cover, rec against rec_regime):", "",
            "| Mode | Target | outputs | rec CRPS | rec_regime CRPS | rec_regime − rec | rec cover | rec_regime cover |",
            "|---|---|---|---|---|---|---|---|"]
    for mode in ("whatif", "lost_82"):
        for g in mb.GROUPS:
            c = np.intersect1d(cols(g), np.flatnonzero(pub))
            if len(c):
                a, b = rgroup(mode, "rec", g), rgroup(mode, "rec_regime", g)
                out.append(f"| {mode} | {g} | {len(c)} | {a:.3f} | {b:.3f} | {b - a:+.3f} | "
                           f"{rgroup(mode, 'rec', g, 'inside'):.0%} | {rgroup(mode, 'rec_regime', g, 'inside'):.0%} |")
    fk = meta["fits"].get("bayes_regime", {})
    if fk.get("kappa"):
        keys = data["target_keys"]
        k, z = fk["kappa"], fk["zeta"]
        out += ["", f"## Disruption multipliers, replay fit (months to {meta['fitted_to']}: learned from 2022 only)", "",
                "Pass-through multiplier 1 + κ and band factor exp(ζ) in D = 1 months: posterior mean and 90% interval.", "",
                "| Series | 1 + κ | exp(ζ) |", "|---|---|---|"]
        for i, key in enumerate(keys):
            out.append(f"| {key} | {1 + k['mean'][i]:.2f} ({1 + k['q05'][i]:.2f}..{1 + k['q95'][i]:.2f}) | "
                       f"{np.exp(z['mean'][i]):.2f} ({np.exp(z['q05'][i]):.2f}..{np.exp(z['q95'][i]):.2f}) |")
    out += cost_lines
    out += ["", "## Sampler health (bayes_regime)", "", "| Fit | Regime | Disruption months | Max R-hat | Min ESS | Divergences |",
            "|---|---|---|---|---|---|"]
    for j, d in enumerate(diags):
        out.append(f"| fold {j} | {'on' if d.get('regime') else 'off'} | {d.get('regime_months', 0)} | {d['max_r_hat']} | "
                   f"{d['min_ess']} | {d['divergences']} |")
    if fk.get("diagnostics"):
        d = fk["diagnostics"]
        out.append(f"| replay | {'on' if d.get('regime') else 'off'} | {d.get('regime_months', 0)} | {d['max_r_hat']} | "
                   f"{d['min_ess']} | {d['divergences']} |")
    (NOTES / "macro-chain-regime.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {NOTES / 'macro-chain-regime.md'}: {'passes' if keep else 'fails'} the keep rule"
          + ("" if keep else f" ({'; '.join(why)})"))


# --- entry -----------------------------------------------------------------------------------

def save_member(S: dict, summary: dict, j: int, member: str) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(RUNS / f"{stem(j, member)}.npz", **S)
    meta = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "job": os.environ.get("SLURM_JOB_ID")}
    (RUNS / f"{stem(j, member)}.json").write_text(json.dumps(summary | {"meta": meta}))


def main() -> None:
    global QUICK
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("check", "fold", "report", "replay", "regime"))
    p.add_argument("j", nargs="?", type=int, default=0)
    p.add_argument("members", nargs="*", help=f"default: every available member ({', '.join(available())}); "
                                              f"also {', '.join(OPTIONAL)} when named")
    a = p.parse_args()
    if a.cmd == "report":
        return report()
    if a.cmd == "replay":
        return replay()
    if a.cmd == "regime":
        return regime_report()
    data = mn.make_dataset(mn.V1_BLOCKS)
    market, (prices, _) = mb.market_inputs(data), op.daily_brent()
    if a.cmd == "check":
        QUICK = mb.QUICK = mg.QUICK = mx.QUICK = True
        for m in ("bayes_own", "global_lin", "xattn"):
            S, summ = run_member(data, mn.FOLDS - 1, m, market, prices)
            print(m, {mode: round(float(np.nanmean(v["crps"])), 4) for mode, v in summ["modes"].items()},
                  {mode: s.shape for mode, s in S.items()}, summ["copula"], flush=True)
        return
    for m in a.members or available():
        assert m in available() or m in OPTIONAL or m == MARGIN, f"{m} is not available in this checkout"
        S, summ = run_member(data, a.j, m, market, prices)
        save_member(S, summ, a.j, m)
        print(f"fold {a.j} {m}: " + ", ".join(f"{mode} {np.nanmean(v['crps']):.4f}" for mode, v in summ["modes"].items())
              + f" ({summ['seconds']}s)", flush=True)


if __name__ == "__main__":
    main()
