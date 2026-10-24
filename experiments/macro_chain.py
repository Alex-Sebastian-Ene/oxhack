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
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import time
from datetime import UTC, datetime

import numpy as np

import copula as cp
import macro_bayes as mb
import macro_global as mg
import macro_nn as mn
import macro_xattn as mx
import oil_paths as op

RUNS, NOTES = mb.RUNS, mb.NOTES
MEMBERS = ("bayes_own", "global_lin", "global", "global_tcn", "xattn")
RECOMMENDED = ("bayes_own", "global_lin", "global")  # the ensemble the earlier runs chose (docs/chain.md)
MODES = ("whatif", "levy", "bootstrap")
JOINT_MODES = ("whatif", "levy")  # modes scored jointly, with independent and copula shocks
STEP = 0.25
# Iridis runs with more networks per variant: CHAIN_SEEDS=20 CHAIN_TAG=s20 (the first 5 networks are
# the default run's, since seeds are base + 100 * variant + s)
TAG = os.environ.get("CHAIN_TAG", "")
SPREAD = np.round(np.arange(0.8, 2.001, 0.05), 2)  # calibration: band widening factors tried
QUICK = False


def stem(j: int, member: str) -> str:
    return f"chain-{j}-{member}" + (f"-{TAG}" if TAG else "")


def suffix() -> str:
    return f"-{TAG}" if TAG else ""


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
    """Fit one member on months 13..last; return (simulate(future, rng) -> [N, origins, outputs], extra info)."""
    if member == "bayes_own":
        post, st_b, info_b, diag = mb.fit(data, last, seed=bayes_seed, vol="own")
        return (lambda fut, rng: mb.simulate(post, st_b, info_b, data, t, fut, rng)), {"diagnostics": diag}
    if member == "xattn":
        nets, training, state = mx.fit_xattn(data, info, st, last, 2 if QUICK else int(os.environ.get("CHAIN_SEEDS", mx.SEEDS)),
                                             base_seed)
        return (lambda fut, rng: mx.simulate(nets, state, st, info, data, t, fut, rng, n=draws())), \
            {"training": training, "context": state["ctx"]["codes"], "context_fetched": state["ctx"]["fetched"]}
    nets, training = fit_nets(data, info, st, last, member, base_seed)
    return (lambda fut, rng: mg.simulate(nets, st, info, data, t, fut, rng, n=draws())), {"training": training}


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
    sim, extra = member_simulator(data, info, st, last, t, member, 1000 * j, bayes_seed=j)  # the seeds of run_fold
    S = {}
    for mode, fut in oil.items():
        S[mode] = sim(fut, np.random.default_rng(300 + j)).astype(np.float32)
        S[f"{mode}_cop"] = sim(fut, cp.CopulaRNG(np.random.default_rng(300 + j), cop)).astype(np.float32)
    summary = {"fold": j, "member": member, "test_dates": [f"{d:%Y-%m}" for d in data["dates"][test]],
               "names": data["names"], "groups": data["groups"], "y": Y.tolist(), "seconds": round(time.time() - t0, 1),
               "copula": {k: v for k, v in cop.items() if k not in ("R", "L")},
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
    members = [m for m in MEMBERS if all((RUNS / f"{stem(j, m)}.npz").exists() for j in range(mn.FOLDS))]
    if not members:
        raise SystemExit(f"no complete runs/macro/{stem(0, '<member>')}.npz set yet")
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
        folds.append({"summ": summ, "S": S, "y": y, "clim": np.array(v1["models"]["climatology"]["crps"], float),
                      "clim_emp": empirical_crps(data["Y"][train], y), "vol": vol})
    names, groups = folds[0]["summ"][members[0]]["names"], np.array(folds[0]["summ"][members[0]]["groups"])
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
                M = mixture(f["S"][mode], w, order)
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
                        e, v = cp.joint_scores(mixture(f["S"][mode + var], W[pick[label]], order), f["y"], scale, H, mn.HORIZONS)
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
           "group, the weights (simplex grid, step 0.25) with the lowest CRPS on earlier folds (equal for fold 0).", ""]
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

REPLAY_ORIGIN = "2026-02"  # the last month before the closure (7-day flow share below 50% from 2026-03-04)
LOSTS = (0.0, 25.0, 50.0, 82.0, 100.0)  # points of Hormuz flow lost; 82 is what happened
SHOWN = ("us_cpi", "uk_cpi", "ea_cpi", "us_rate", "ind_gasdesw", "ind_djfuelusgulf", "ind_pcu324110324110",
         "ind_pcu325311325311")


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
    assert all(m in available() for m in members), f"{members}: not all available ({available()})"
    equal = np.full(len(members), 1 / len(members))
    real = data["oil_m"][m + 1:m + 1 + mn.OIL_AHEAD]
    seen = int(np.isfinite(real).sum())
    oil = {"whatif": np.nan_to_num(np.r_[real, np.full(mn.OIL_AHEAD - len(real), np.nan)])[None, None]}
    for lost in LOSTS:
        oil[f"lost {lost:g}"] = op.monthly_paths(prices, idx[t], mb.DRAWS, np.random.default_rng(900), "cgmy",
                                                 market["drift"][t], lost=lost)
    cop = cp.fit(data, st, last, info)
    S = {mode: [] for mode in oil}
    S_cop = {mode: [] for mode in ("whatif", f"lost {op.LOST_2026:g}")}
    for mm in members:
        sim, extra = member_simulator(data, info, st, last, t, mm, 90_000, bayes_seed=99)
        if "diagnostics" in extra:
            print(f"replay {mm}: {extra['diagnostics']}", flush=True)
        for mode, fut in oil.items():
            S[mode].append(sim(fut, np.random.default_rng(300))[:, 0])  # [N, outputs]
            if mode in S_cop:
                S_cop[mode].append(sim(fut, cp.CopulaRNG(np.random.default_rng(300), cop))[:, 0])
    names, groups = data["names"], np.array(data["groups"])
    order = np.random.default_rng(1234).permutation(mb.DRAWS)
    ens = {}
    for mode, parts in S.items():
        ens[mode] = mixture(np.stack(parts), equal, order)  # [N, outputs]
    ens_cop = {mode: mixture(np.stack(parts), equal, order) for mode, parts in S_cop.items()}
    # what happened: the change over h months after the origin, where every month is published
    dM = data["dM"]
    actual = {}
    for c, nm in enumerate(names):
        key, h = nm.split("@")
        k, h = data["target_keys"].index(key), int(h)
        seg = dM[m + 1:m + 1 + h, k]
        actual[nm] = float(seg.sum()) if len(seg) == h and np.isfinite(seg).all() else np.nan

    gen = datetime.now(UTC).date().isoformat()
    lines = [f"# Replaying the 2026 Hormuz closure from {origin}", "",
             f"_Generated by `experiments/macro_chain.py replay` on {gen}. Every model is fitted on months up to "
             f"{idx[last]:%Y-%m} only. Outcomes are real (`notes/macro-panel.md`; daily Brent FRED DCOILBRENTEU "
             f"fetched {fetched}); {seen} months of Brent after the origin are known. Members: {', '.join(members)}, "
             "mixed with equal weights, the best ensemble on the 8 folds (`notes/macro-chain-results.md`). "
             "Simulated: the oil paths and the model draws._", "",
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

    rows = ["series,group,flow_drop_points,months_ahead,mean,q05,q50,q95,actual,unit,validated,origin,source,fitted_to,generated"]
    for c, nm in enumerate(names):
        key, h = nm.split("@")
        grp = groups[c]
        unit = "pp" if grp in ("unemployment", "rate") else "100 x log change (about %)"
        validated = "yes" if grp in ("inflation", "cost") else "no (no causal oil link; forecast only)"
        for lost in LOSTS:
            x = ens[f"lost {lost:g}"][:, c]
            q05, q50, q95 = np.quantile(x, [0.05, 0.5, 0.95])
            a = actual[nm]
            rows.append(f"{key},{grp},{lost:g},{h},{x.mean():.4f},{q05:.4f},{q50:.4f},{q95:.4f},"
                        f"{'' if not np.isfinite(a) else f'{a:.4f}'},{unit},{validated},{origin},"
                        "experiments/macro_chain.py replay (oil: GARCH-CGMY + notes/flow-premium.csv premium sampled in its band; "
                        f"models: {'+'.join(members)}),{idx[last]:%Y-%m},{gen}")
    (NOTES / f"chain-scenarios{suffix()}.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"wrote {NOTES / f'chain-replay-2026{suffix()}.md'} and {NOTES / f'chain-scenarios{suffix()}.csv'}")


# --- entry -----------------------------------------------------------------------------------

def save_member(S: dict, summary: dict, j: int, member: str) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(RUNS / f"{stem(j, member)}.npz", **S)
    meta = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "job": os.environ.get("SLURM_JOB_ID")}
    (RUNS / f"{stem(j, member)}.json").write_text(json.dumps(summary | {"meta": meta}))


def main() -> None:
    global QUICK
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("check", "fold", "report", "replay"))
    p.add_argument("j", nargs="?", type=int, default=0)
    p.add_argument("members", nargs="*", help=f"default: every available member ({', '.join(available())})")
    a = p.parse_args()
    if a.cmd == "report":
        return report()
    if a.cmd == "replay":
        return replay()
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
        assert m in available(), f"{m} is not available in this checkout"
        S, summ = run_member(data, a.j, m, market, prices)
        save_member(S, summ, a.j, m)
        print(f"fold {a.j} {m}: " + ", ".join(f"{mode} {np.nanmean(v['crps']):.4f}" for mode, v in summ["modes"].items())
              + f" ({summ['seconds']}s)", flush=True)


if __name__ == "__main__":
    main()
