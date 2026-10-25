# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scipy>=1.11", "xlrd>=2.0", "openpyxl>=3.1", "torch>=2.2",
#                 "jax>=0.4.30", "numpyro>=0.15"]
# ///
"""Industries by country: does the global one-step network of experiments/macro_global.py forecast
mining, refining and metals industries across countries, and world metal prices, as it does the 22
macro targets?

Targets (experiments/macro_data.py, SECTOR_BLOCKS), each a series of the shared network:
    price       producer prices of 20 industries (coal, oil and gas, metal ores, other mining, oil
                refining, chemicals, fertilisers, plastics, paper, cement, basic metals, iron and steel,
                non-ferrous metal refining, aluminium, copper, lead/zinc/tin, foundries, electricity,
                all manufacturing) in every country that publishes them for 10+ years: Eurostat for
                about 30 European countries, FRED (BLS) for the closest US industries
    output      the same industries' output (volume indices; Fed industrial production for the US)
    commodity   9 world mineral prices (IMF via FRED): copper, aluminium, nickel, zinc, lead, tin,
                iron ore, coal, uranium

The model, its training and the what-if simulation are macro_global.py's, unchanged:
    global        one network shared by every series: the series' own last 12 monthly changes,
                  Brent's monthly change at lags 0-12, the oil volatility state, a series embedding,
                  and a Student-t head
    global_lin    plus a per-series linear term in the location
    global_nooil  the global network with its oil inputs (lags and volatility state) set to 0 in
                  training and simulation: how much of the skill comes from knowing oil
Benchmarks:
    climatology   Gaussian at each output's mean and sd over the fold's training origins
    ols           per-series least squares on the network's inputs (macro_global.OLS)
    ols_small     the same on 4 of them (own last change, Brent lags 0-2): the full OLS has 27
                  coefficients per series and overfits 80-280 months (`benchmarks`)

Folds are macro_nn.py's (8 forward-chaining test blocks from 2008, 12-month gap). An output is
scored in a fold only if its series has MIN_TRAIN monthly changes in the fold's training months.
With about 600 series there are about 25 times the macro run's training rows, so the batch is
larger (BATCH) and forecasts are simulated a few origins at a time (CHUNK).

    uv run experiments/sector_global.py check      # tiny end-to-end run on the last fold
    uv run experiments/sector_global.py fold 3     # one fold -> runs/macro/sector-fold-3.json
    uv run experiments/sector_global.py benchmarks # the small OLS on every fold -> runs/macro/sector-benchmarks.json
    uv run experiments/sector_global.py report     # notes/sector-global-results.md
"""

from __future__ import annotations

import argparse
import json
import os
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
from torch import nn

import macro_bayes as mb
import macro_data as md
import macro_global as mg
import macro_nn as mn

ROOT = Path(__file__).resolve().parent.parent
RUNS, NOTES = ROOT / "runs" / "macro", ROOT / "notes"
VARIANTS = ("global", "global_lin", "global_nooil")
MODELS = (*VARIANTS, "ols", "climatology")
GROUPS = ("price", "output", "commodity")
MIN_TRAIN = 60  # monthly changes a series needs in a fold's training months to be scored there
BATCH = 1024
CHUNK = 4  # forecast origins simulated at once (memory: draws x origins x series x inputs)
OIL = slice(mg.OWN, mg.OWN + mb.LAGS + 1)  # Brent lags 0-12 and the volatility state in the inputs
mg.TRAIN = mg.TRAIN | {"batch": BATCH}


class NoOil(nn.Module):
    """A trained network that never sees oil: its oil inputs are set to 0 (no change, average
    volatility) before every forward pass, as they were in training."""

    def __init__(self, net: nn.Module) -> None:
        super().__init__()
        self.net = net

    def forward(self, x, k):
        x = x.clone()
        x[:, OIL] = 0.0
        return self.net(x, k)


def dataset() -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return mn.make_dataset(md.SECTOR_BLOCKS)


def stats(data: dict, last: int) -> mb.Stats:
    """macro_bayes.Stats, with series that have no (or constant) training months left unscaled."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        st = mb.Stats(data, last)
    bad = ~np.isfinite(st.ys) | (st.ys < 1e-6)
    st.ym, st.ys = np.where(bad, 0.0, st.ym), np.where(bad, 1.0, st.ys)
    return st


def simulate(nets: list, st, info: dict, data: dict, t: np.ndarray, future: np.ndarray, rng, **kw) -> np.ndarray:
    """macro_global.simulate, CHUNK origins at a time."""
    return np.concatenate([mg.simulate(nets, st, info, data, t[i:i + CHUNK], future[:, i:i + CHUNK], rng, **kw)
                           for i in range(0, len(t), CHUNK)], 1)


def run_fold(data: dict, j: int) -> dict:
    dates, names = data["dates"], data["names"]
    train, test, last = mb.fold_window(data, j)
    info, st = mb.series_info(data), stats(data, last)
    months, k, x, y = mg.training_rows(mg.features(data, st), last)
    n_train = np.isfinite(data["dM"][13:last + 1]).sum(0)
    scored = np.repeat(n_train >= MIN_TRAIN, len(mn.HORIZONS))  # per output, target-major as names
    print(f"fold {j}: train months to {last} ({len(y)} rows, {int((n_train >= MIN_TRAIN).sum())} of "
          f"{len(n_train)} series scored), test {dates[test[0]]:%Y-%m}..{dates[test[-1]]:%Y-%m}", flush=True)
    t, Y, oil = data["t"][test], data["Y"][test], data["OIL"][test]
    Ys = np.where(scored, Y, np.nan)
    shocked = oil.copy()
    shocked[:, 0] += mg.SHOCK
    draws = 50 if mg.QUICK else mb.DRAWS

    def rounded(d: dict) -> dict:
        return {key: np.round(np.asarray(v, float), 4).tolist() for key, v in d.items() if key != "mu"}

    out = {"fold": j, "test_dates": [f"{d:%Y-%m}" for d in dates[test]], "names": names, "groups": data["groups"],
           "scored": scored.tolist(), "y": np.round(Ys, 4).tolist(), "train_months_to": int(last), "models": {}}
    for vi, variant in enumerate(VARIANTS):
        t0 = time.time()
        xv = x.copy()
        if variant == "global_nooil":
            xv[:, OIL] = 0.0
        fitted = [mg.train(xv, k, y, months, info["floor"], variant == "global_lin", seed=1000 * j + 100 * vi + s)
                  for s in range(2 if mg.QUICK else mg.SEEDS)]
        nets = [NoOil(f[0]) if variant == "global_nooil" else f[0] for f in fitted]
        S = simulate(nets, st, info, data, t, oil[None], np.random.default_rng(300 + j), n=draws)
        base = simulate(nets, st, info, data, t, oil[None], None, n=len(nets), noise=False)
        up = simulate(nets, st, info, data, t, shocked[None], None, n=len(nets), noise=False)
        out["models"][variant] = rounded(mb.summarise(S, Ys)) | {
            "training": [f[1] for f in fitted], "seconds": round(time.time() - t0, 1),
            "response_up10": np.round((up - base).mean((0, 1)), 4).tolist()}
        print(f"  {variant}: best epochs {[f[1]['best_epoch'] for f in fitted]}, CRPS "
              f"{np.nanmean(out['models'][variant]['crps']):.4f} ({time.time() - t0:.0f}s)", flush=True)
        del S
    S = simulate([mg.OLS(x, k, y, info["floor"])], st, info, data, t, oil[None], np.random.default_rng(500 + j),
                 n=draws)
    out["models"]["ols"] = rounded(mb.summarise(S, Ys))
    del S
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mu, sd = np.nanmean(data["Y"][train], 0), np.nanstd(data["Y"][train], 0)
    crps = np.where(np.isfinite(Ys), mb.gaussian_crps(mu, sd, np.nan_to_num(Ys)), np.nan)
    z = 1.6448536269514722  # 90% central interval of a Gaussian
    out["models"]["climatology"] = rounded({"crps": crps, "q05": np.broadcast_to(mu - z * sd, Y.shape),
                                            "q95": np.broadcast_to(mu + z * sd, Y.shape)})
    print(f"  ols CRPS {np.nanmean(out['models']['ols']['crps']):.4f}, climatology "
          f"{np.nanmean(out['models']['climatology']['crps']):.4f}", flush=True)
    return out


class SmallOLS(nn.Module):
    """Per-series least squares on 4 of the network's inputs (own last change, Brent lags 0-2): the
    full OLS has 27 coefficients per series, too many for 80-280 months, and overfits."""

    KEEP = [0, mg.OWN, mg.OWN + 1, mg.OWN + 2]

    def __init__(self, x: np.ndarray, k: np.ndarray, y: np.ndarray, floor: np.ndarray) -> None:
        super().__init__()
        mask = np.zeros(x.shape[1])
        mask[self.KEEP] = 1.0
        self.ols, self.mask = mg.OLS(x * mask, k, y, floor), torch.as_tensor(mask, dtype=torch.float32)

    def forward(self, x, k):
        return self.ols(x * self.mask, k)


def run_benchmarks(data: dict) -> dict:
    """The small OLS on every fold, scored on the same outputs as run_fold (no training loop)."""
    folds = []
    for j in range(mn.FOLDS):
        _, test, last = mb.fold_window(data, j)
        info, st = mb.series_info(data), stats(data, last)
        months, k, x, y = mg.training_rows(mg.features(data, st), last)
        scored = np.repeat(np.isfinite(data["dM"][13:last + 1]).sum(0) >= MIN_TRAIN, len(mn.HORIZONS))
        Ys = np.where(scored, data["Y"][test], np.nan)
        S = simulate([SmallOLS(x, k, y, info["floor"])], st, info, data, data["t"][test], data["OIL"][test][None],
                     np.random.default_rng(700 + j))
        r = mb.summarise(S, Ys)
        folds.append({"fold": j, "test_dates": [f"{d:%Y-%m}" for d in data["dates"][test]]}
                     | {key: np.round(np.asarray(r[key], float), 4).tolist() for key in ("crps", "q05", "q95")})
        print(f"ols_small fold {j}: CRPS {np.nanmean(folds[-1]['crps']):.4f}", flush=True)
    return {"folds": folds}


# --- report ----------------------------------------------------------------------------------

def report() -> None:
    folds = [f for j in range(mn.FOLDS) if (f := mb.load(f"sector-fold-{j}.json"))]
    if not folds:
        raise SystemExit("no runs/macro/sector-fold-*.json yet")
    names = folds[0]["names"]
    for f in folds:
        assert f["names"] == names, f"sector-fold-{f['fold']}: outputs differ"
    keys = [n.split("@")[0] for n in names[::len(mn.HORIZONS)]]
    groups = np.array(folds[0]["groups"])
    H = np.array([int(n.split("@")[1]) for n in names])
    out_key = np.array([n.split("@")[0] for n in names])
    reg = {s.key: s for s in md.registry(md.ALL_BLOCKS)}
    sector = {s.key: s.code.split(":")[2] if s.source == "eurostat_sectors" else s.key.split("_")[-1].upper()
              for s in reg.values() if s.block == "sectors"}
    geo = {s.key: s.code.split(":")[1] if s.source == "eurostat_sectors" else "US"
           for s in reg.values() if s.block == "sectors"}
    industry = {nace: name for nace, name, *_ in md.SECTORS}
    countries = md.COUNTRIES | {"US": "United States"}

    def stack(get):
        return np.vstack([np.array(get(f), float) for f in folds])

    for f in folds:
        f["models"] = {m: f["models"][m] for m in MODELS}
    bench = mb.load("sector-benchmarks.json")
    bench = {b["fold"]: b for b in bench["folds"]} if bench else {}
    if all(f["fold"] in bench for f in folds):
        for f in folds:
            assert bench[f["fold"]]["test_dates"] == f["test_dates"], f"sector-benchmarks fold {f['fold']}: origins differ"
            f["models"]["ols_small"] = bench[f["fold"]]
    models = [m for m in (*VARIANTS, "ols", "ols_small", "climatology") if m in folds[0]["models"]]
    C = {m: stack(lambda f, m=m: f["models"][m]["crps"]) for m in models}
    scale = np.nanmean(C["climatology"], 0)
    labels = {"global": "global", "global_lin": "global_lin", "global_nooil": "global, no oil",
              "ols": "OLS, same inputs", "ols_small": "OLS, small", "climatology": "climatology"}

    def ratios(m, c):
        """Per output: mean CRPS over the test origins / climatology's."""
        c = c[np.isfinite(scale[c]) & (scale[c] > 0)]
        return np.nanmean(C[m][:, c], 0) / scale[c]

    def skill(m, c):
        r = ratios(m, c)
        return 1 - np.nanmean(r) if len(r) else np.nan

    def cols(**kw):
        ok = np.ones(len(names), bool)
        if "group" in kw:
            ok &= groups == kw["group"]
        if "h" in kw and kw["h"] != "all":
            ok &= H == kw["h"]
        if "sector" in kw:
            ok &= np.array([sector.get(k) == kw["sector"] for k in out_key])
        if "geo" in kw:
            ok &= np.array([geo.get(k) == kw["geo"] for k in out_key])
        if "key" in kw:
            ok &= out_key == kw["key"]
        return np.flatnonzero(ok)

    def n_series(c):
        return len({out_key[i] for i in c if np.isfinite(scale[i])})

    first, last = folds[0]["test_dates"][0], folds[-1]["test_dates"][-1]
    n_orig = sum(len(f["test_dates"]) for f in folds)
    scored_keys = [k for k in keys if np.isfinite(scale[names.index(f"{k}@1")])]
    cnt = {g: sum(reg[k].target == g for k in scored_keys) for g in GROUPS}
    eu = sorted({geo[k] for k in scored_keys if k in geo and geo[k] != "US"})
    rows = [f["models"]["global"]["training"][0]["rows"] for f in folds]
    when = sorted(f["meta"]["generated"] for f in folds if "meta" in f)
    out = [
        "# Industries by country: global network results", "",
        f"_Generated by `experiments/sector_global.py report` on {datetime.now(UTC).date().isoformat()} from "
        f"{len(folds)} forward-chaining folds ({first}..{last}, {n_orig} forecast origins), the folds of "
        "`notes/macro-global-results.md`. Fold files generated "
        + (f"{when[0]} to {when[-1]}" if when else "(no timestamps)")
        + ". Data: Eurostat `sts_inppd_m` (domestic producer prices) and `sts_inpr_m` (output, seasonally and "
        "calendar adjusted), FRED (BLS PPIs, Fed industrial production, IMF metal prices), fetched by "
        "`experiments/macro_data.py`; real and revised (not real-time vintages); nothing is synthetic. Every "
        "forecast here is a **what-if**: it is given the oil path that happened._", "",
        f"**Series scored:** {cnt['price']} producer-price series and {cnt['output']} output series ({len(eu)} "
        f"European countries and the US, {len(md.SECTORS)} industries), and {cnt['commodity']} world mineral "
        f"prices. One network is shared by all of them; training rows per fold run from {rows[0]:,} to "
        f"{rows[-1]:,} (the macro run had 1,682 to 5,818). A series is scored in a fold only if it has "
        f"{MIN_TRAIN}+ monthly changes in that fold's training months.", "",
        "Skill = 1 − CRPS / CRPS of climatology (each output's training mean and spread), averaged over the "
        "outputs in the row; 0 is no better than climatology. `global, no oil` is the same network with its "
        "oil inputs set to 0, so `global` minus `global, no oil` is what knowing oil adds. `OLS, same inputs` "
        "is per-series least squares on all 26 network inputs; `OLS, small` uses 4 of them (own last change, "
        "Brent lags 0–2), which is all 80–280 months per series can support.", ""]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        _, _, prov = md.build_panel(md.SECTOR_BLOCKS)  # from the cache in data/raw/macro/
    kept = {p["series"].key: p for p in prov if "error" not in p and p["series"].block == "sectors"}
    n_skipped = sum(p["error"].startswith("skipped") for p in prov if "error" in p)
    files = [*md.RAW.glob("eurostat_sectors_*.json"),
             *(md.RAW / f"fred_{s.code}.csv" for s in reg.values() if s.block in md.SECTOR_BLOCKS[1:] and s.source == "fred")]
    fetched = sorted({datetime.fromtimestamp(f.stat().st_mtime, UTC).date().isoformat() for f in files if f.exists()})
    out += ["## Data", "",
            f"Fetched {fetched[0]}" + (f" to {fetched[-1]}" if fetched[-1] != fetched[0] else "") + ". "
            f"Every industry is asked for in all {len(md.COUNTRIES)} European countries and the US; a pair enters "
            f"if it has {md.SECTOR_MIN_MONTHS}+ months from {md.START[:4]} and data after {md.SECTOR_LIVE_FROM[:7]} "
            f"({n_skipped} published pairs were too short or stopped; the rest aren't published). Publication lags: "
            "2 months for Eurostat, 1 for FRED. US series are the closest NAICS industries, not exact matches.", "",
            "| Industry | NACE | Price: countries | Output: countries | Earliest month | Latest month |",
            "|---|---|---|---|---|---|"]
    for nace, name, *_ in md.SECTORS:
        ps = [p for k, p in kept.items() if sector[k] == nace]
        if not ps:
            continue
        n = {g: sum(p["series"].target == g for p in ps) for g in ("price", "output")}
        out.append(f"| {name} | {nace} | {n['price']} | {n['output']} | {min(p['first'] for p in ps):%Y-%m} | "
                   f"{max(p['last'] for p in ps):%Y-%m} |")
    out.append("")

    shown = [m for m in models if m != "climatology"]
    out += ["## Skill by horizon", "", "| Target | h | " + " | ".join(labels[m] for m in shown) + " |",
            "|---|---|" + "---|" * len(shown)]
    for grp in GROUPS:
        for h in [*mn.HORIZONS, "all"]:
            b = "**" if h == "all" else ""
            out.append(f"| {grp} | {h} | " + " | ".join(f"{b}{skill(m, cols(group=grp, h=h)):+.3f}{b}" for m in shown)
                       + " |")

    out += ["", "## How robust is the average?", "",
            "The skill above is a mean of per-output ratios (model CRPS / climatology CRPS), so a few outputs where a "
            "model blows up can drag it down. Here, over all horizons: the mean, the median, and the share of outputs "
            "where the model beats climatology.", "",
            "| Target | " + " | ".join(f"{labels[m]}: mean / median / share better" for m in shown) + " |",
            "|---|" + "---|" * len(shown)]
    for grp in GROUPS:
        cells = []
        for m in shown:
            r = ratios(m, cols(group=grp))
            cells.append(f"{1 - np.nanmean(r):+.3f} / {1 - np.nanmedian(r):+.3f} / {np.mean(r[np.isfinite(r)] < 1):.0%}")
        out.append(f"| {grp} | " + " | ".join(cells) + " |")

    def by(field: str, values, grp: str, label) -> list[str]:
        lines = [f"| {label(v)} | {n_series(c)} | " + " | ".join(f"{skill(m, c):+.3f}" for m in shown)
                 + f" | {skill('global', c) - skill('global_nooil', c):+.3f} |"
                 for v in values if n_series(c := cols(group=grp, **{field: v}))]
        return lines

    head = " | ".join(labels[m] for m in shown)
    for grp, what in (("price", "producer prices"), ("output", "output")):
        out += ["", f"## {what.capitalize()} by industry (all horizons)", "",
                f"| Industry | Series | {head} | oil adds |", "|---|---|" + "---|" * (len(shown) + 1)]
        out += by("sector", [s[0] for s in md.SECTORS], grp, lambda v: f"{industry[v]} ({v})")
    for grp, what in (("price", "producer prices"), ("output", "output")):
        out += ["", f"## {what.capitalize()} by country (all industries, all horizons)", "",
                f"| Country | Series | {head} | oil adds |", "|---|---|" + "---|" * (len(shown) + 1)]
        out += by("geo", ["US", *md.COUNTRIES], grp, lambda v: countries[v])
    out += ["", "## World mineral prices (all horizons)", "",
            f"| Price | {head} | oil adds |", "|---|" + "---|" * (len(shown) + 1)]
    for key in [k for k in keys if reg[k].target == "commodity"]:
        c = cols(key=key)
        out.append(f"| {reg[key].name} | " + " | ".join(f"{skill(m, c):+.3f}" for m in shown)
                   + f" | {skill('global', c) - skill('global_nooil', c):+.3f} |")

    best = "global_lin"
    per = sorted(((skill(best, cols(key=k)), k) for k in scored_keys if reg[k].target != "commodity"), reverse=True)
    out += ["", f"## Best and worst forecast series ({labels[best]}, all horizons)", "",
            "| | Series | Skill |", "|---|---|---|"]
    out += [f"| best {i + 1} | {reg[k].name} | {s:+.3f} |" for i, (s, k) in enumerate(per[:8])]
    out += [f"| worst {i + 1} | {reg[k].name} | {s:+.3f} |" for i, (s, k) in enumerate(per[::-1][:8])]

    y_all = stack(lambda f: f["y"])
    out += ["", "## Calibration: share of outcomes inside the central 90% interval (target 90%)", "",
            "| Target | " + " | ".join(labels[m] for m in models) + " |", "|---|" + "---|" * len(models)]
    for grp in GROUPS:
        c = cols(group=grp)
        ok = np.isfinite(y_all[:, c])
        cells = []
        for m in models:
            lo, hi = stack(lambda f: f["models"][m]["q05"])[:, c], stack(lambda f: f["models"][m]["q95"])[:, c]
            cells.append(f"{np.mean(((y_all[:, c] >= lo) & (y_all[:, c] <= hi))[ok]):.0%}")
        out.append(f"| {grp} | " + " | ".join(cells) + " |")

    pairs = [("global", "climatology"), ("global_lin", "climatology"), ("global", "ols"),
             *([("global", "ols_small")] if "ols_small" in models else []), ("global_lin", "global"),
             ("global", "global_nooil")]
    out += ["", "## Are the differences real? Diebold–Mariano tests", "",
            "Mean difference in climatology-scaled CRPS over all horizons and the group's outputs (negative: the "
            "first model is better), with its Newey–West t-statistic (12 lags) over forecast origins. |t| > 2 is "
            "roughly significant at 5%.", "",
            "| Comparison | " + " | ".join(GROUPS) + " |", "|---|" + "---|" * len(GROUPS)]
    for m1, m2 in pairs:
        cells = []
        for grp in GROUPS:
            c = cols(group=grp)
            c = c[np.isfinite(scale[c]) & (scale[c] > 0)]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                d = np.nanmean((C[m1][:, c] - C[m2][:, c]) / scale[c], 1)
            d = d[np.isfinite(d)]
            cells.append(f"{np.mean(d):+.3f} (t {mb.nw_t(d):+.1f})")
        out.append(f"| {labels[m1]} vs {labels[m2]} | " + " | ".join(cells) + " |")

    out += ["", "## Did the networks train?", "",
            "Epoch with the lowest validation NLL (last quarter of the training months) per seed.", "",
            "| Fold | Training rows | " + " | ".join(f"{labels[m]}: best epochs" for m in VARIANTS) + " | Minutes |",
            "|---|---|" + "---|" * (len(VARIANTS) + 1)]
    for f in folds:
        tr = {m: f["models"][m]["training"] for m in VARIANTS}
        mins = sum(f["models"][m]["seconds"] for m in VARIANTS) / 60
        out.append(f"| {f['fold']} | {tr[VARIANTS[0]][0]['rows']:,} | "
                   + " | ".join(", ".join(str(s["best_epoch"]) for s in tr[m]) for m in VARIANTS) + f" | {mins:.0f} |")

    # mean over the folds where the output was scored (a series without training months has an untrained embedding)
    seen = stack(lambda f: f["scored"]).astype(bool)
    R = {m: np.nanmean(np.where(seen, stack(lambda f, m=m: f["models"][m]["response_up10"]), np.nan), 0)
         for m in ("global", "global_lin")}
    out += ["", "## Response to +10% Brent in the next month, 12 months on", "",
            "Location-only paths with and without the shock, on top of the oil path that happened, averaged over "
            "each fold's test origins and networks, then over folds; in % of the price or output level. For each "
            "industry: the median over the countries that publish it, the middle 80% of countries, and the US.", "",
            "| Industry | Target | Countries | global_lin median | 10th–90th percentile | US | global median |",
            "|---|---|---|---|---|---|---|"]
    for nace, name, *_ in md.SECTORS:
        for grp in ("price", "output"):
            ks = [k for k in scored_keys if reg[k].target == grp and sector.get(k) == nace]
            if not ks:
                continue
            r = {m: np.array([R[m][names.index(f"{k}@12")] for k in ks]) for m in R}
            us = f"{grp}_us_{nace.lower()}"
            us_r = f"{R['global_lin'][names.index(f'{us}@12')]:+.1f}" if us in ks else "–"
            lo, hi = np.percentile(r["global_lin"], [10, 90])
            out.append(f"| {name} ({nace}) | {grp} | {len(ks)} | {np.median(r['global_lin']):+.1f} | "
                       f"{lo:+.1f} to {hi:+.1f} | {us_r} | {np.median(r['global']):+.1f} |")
    for key in [k for k in keys if reg[k].target == "commodity"]:
        c = names.index(f"{key}@12")
        out.append(f"| {reg[key].name} | commodity | | {R['global_lin'][c]:+.1f} | | | {R['global'][c]:+.1f} |")
    (NOTES / "sector-global-results.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {NOTES / 'sector-global-results.md'}")


# --- entry -----------------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("check", "fold", "benchmarks", "report"))
    p.add_argument("j", nargs="?", type=int, default=0)
    a = p.parse_args()
    if a.cmd == "report":
        return report()
    data = dataset()
    if a.cmd == "benchmarks":
        RUNS.mkdir(parents=True, exist_ok=True)
        (RUNS / "sector-benchmarks.json").write_text(json.dumps(run_benchmarks(data)))
        return print(f"wrote {RUNS / 'sector-benchmarks.json'}")
    if a.cmd == "check":
        mg.QUICK = True
        out = run_fold(data, mn.FOLDS - 1)
        print({m: float(np.nanmean(v["crps"])) for m, v in out["models"].items()})
        return
    RUNS.mkdir(parents=True, exist_ok=True)
    meta = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "job": os.environ.get("SLURM_JOB_ID")}
    path = RUNS / f"sector-fold-{a.j}.json"
    path.write_text(json.dumps(run_fold(data, a.j) | {"meta": meta}))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
