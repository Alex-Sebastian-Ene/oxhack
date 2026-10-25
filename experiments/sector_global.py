# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scipy>=1.11", "xlrd>=2.0", "openpyxl>=3.1", "torch>=2.2",
#                 "jax>=0.4.30", "numpyro>=0.15"]
# ///
"""Industries and goods by country: does the global one-step network of experiments/macro_global.py
forecast them, and world prices, as it does the 22 macro targets?

Five sets of targets (experiments/macro_data.py), each run separately, each series a series of the
shared network:

  --set sectors (SECTOR_BLOCKS)
    price       producer prices of 20 industries (coal, oil and gas, metal ores, other mining, oil
                refining, chemicals, fertilisers, plastics, paper, cement, basic metals, iron and steel,
                non-ferrous metal refining, aluminium, copper, lead/zinc/tin, foundries, electricity,
                all manufacturing) in every country that publishes them for 10+ years: Eurostat for
                about 30 European countries, FRED (BLS) for the closest US industries
    output      the same industries' output (volume indices; Fed industrial production for the US)
    commodity   9 world mineral prices (IMF via FRED)

  --set nations (NATION_BLOCKS)
    headline, energy, utilities, food, producer
                consumer prices (headline, energy, food; housing and utilities where the database has no
                energy index) and producer prices in about 170 countries, from the World Bank's Global
                Database of Inflation (its vintage ends at 2025-03)

  --set oilflows (OILFLOW_BLOCKS)
    production, imports, exports, refining, demand
                crude and oil product flows in about 115 countries (JODI), thousand barrels a day

  --set markets (MARKET_BLOCKS)
    commodity   every world price (World Bank, IMF, EIA refined products, FAO food indices), broken
                down by kind of commodity

  --set goods (GOODS_BLOCKS)
    price       producer prices of 30 specific goods (the finest NACE classes: plastics in primary
                forms, fertilisers, cement, flat glass, paper, sugar, flour, ...) by European country,
                and 46 US goods (BLS commodity PPIs: diesel, jet fuel, resins, steel mill products,
                copper wire, cement, ...)
    output      the 30 European goods' output by country
    consumer    15 household goods' consumer prices (HICP: motor fuels, diesel, petrol, heating oil,
                gas, electricity, bread, meat, dairy, oils, sugar, rail and air fares) in 37 countries
    commodity   about 50 world prices (World Bank Pink Sheet: fertilisers, grains, oils, sugar, coffee,
                rubber, timber, metals, coal, gas)

The model, its training and the what-if simulation are macro_global.py's, unchanged:
    global        one network shared by every series: the series' own last 12 monthly changes,
                  Brent's monthly change at lags 0-12, the oil volatility state, a series embedding,
                  and a Student-t head
    global_lin    plus a per-series linear term in the location (sectors only: with hundreds of
                  series it overfits by epoch 1-3)
    global_nooil  the global network with its oil inputs (lags and volatility state) set to 0 in
                  training and simulation: how much of the skill comes from knowing oil
Benchmarks:
    climatology   Gaussian at each output's mean and sd over the fold's training origins
    ols           per-series least squares on the network's inputs (macro_global.OLS)
    ols_small     the same on 4 of them (own last change, Brent lags 0-2): the full OLS has 27
                  coefficients per series and overfits 80-280 months (`benchmarks`)

Folds are macro_nn.py's (8 forward-chaining test blocks from 2008, 12-month gap). An output is
scored in a fold only if its series has MIN_TRAIN monthly changes in the fold's training months.
With hundreds of series there are 25-40 times the macro run's training rows, so the batch is larger
(BATCH) and forecasts are simulated and scored a few origins at a time (CHUNK).

    uv run experiments/sector_global.py check [--set goods|nations]  # tiny end-to-end run on the last fold
    uv run experiments/sector_global.py fold 3 [--set goods]       # -> runs/macro/{sector,goods}-fold-3.json
    uv run experiments/sector_global.py benchmarks [--set goods]   # the small OLS on every fold
    uv run experiments/sector_global.py report [--set goods]       # notes/{sector,goods}-global-results.md
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
import pandas as pd
import torch
from torch import nn

import macro_bayes as mb
import macro_data as md
import macro_global as mg
import macro_nn as mn

ROOT = Path(__file__).resolve().parent.parent
RUNS, NOTES = ROOT / "runs" / "macro", ROOT / "notes"
SETS = {
    "sectors": {"blocks": md.SECTOR_BLOCKS, "stem": "sector", "title": "Industries by country", "word": "Industry", "words": "industries",
                "variants": ("global", "global_lin", "global_nooil"), "groups": ("price", "output", "commodity"),
                "items": {"price": [s[:2] for s in md.SECTORS], "output": [s[:2] for s in md.SECTORS]},
                "files": ("eurostat_sectors_*.json",),
                "sources": "Eurostat `sts_inppd_m` (domestic producer prices) and `sts_inpr_m` (output, seasonally and "
                           "calendar adjusted), FRED (BLS PPIs, Fed industrial production, IMF metal prices)"},
    "goods": {"blocks": md.GOODS_BLOCKS, "stem": "goods", "title": "Goods by country", "word": "Good", "words": "goods",
              "variants": ("global", "global_nooil"), "groups": ("price", "output", "consumer", "commodity"),
              "items": {"price": md.GOODS + md.US_GOODS, "output": md.GOODS, "consumer": md.HOUSEHOLD},
              "files": ("eurostat_goods_*.json", "eurostat_household_*.json", "worldbank_cmo_monthly.xlsx"),
              "sources": "Eurostat `sts_inppd_m` and `sts_inpr_m` at the finest NACE classes (producer prices and "
                         "output), Eurostat `prc_hicp_minr` (consumer prices, COICOP 2018), FRED (BLS commodity "
                         "PPIs), World Bank Pink Sheet (monthly world prices)"},
    "nations": {"blocks": md.NATION_BLOCKS, "stem": "nations", "title": "Prices by nation", "word": "Measure",
                "words": "measures", "variants": ("global", "global_nooil"),
                "groups": tuple(g for _, g, _ in md.NATION_MEASURES),
                "items": {g: [(sheet, measure[0].upper() + measure[1:])] for sheet, g, measure in md.NATION_MEASURES},
                "files": ("worldbank_inflation.xlsx",),
                "sources": "the World Bank's Global Database of Inflation (Ha, Kose and Ohnsorge: monthly headline, "
                           "energy and food consumer prices and producer prices, compiled from national sources and "
                           "the IMF; the vintage used ends at 2025-03)",
                "coverage": f"Every measure is asked for in each of the {len(md.NATIONS)} countries in "
                            f"`macro_data.NATIONS`; a series enters if it has {md.SECTOR_MIN_MONTHS}+ months from "
                            f"{md.START[:4]} and data from {md.NATIONS_LIVE_FROM[:7]} on, since the database ends at "
                            "2025-03 ({skipped} published series were too short or stopped; the rest aren't "
                            "published). Publication lag: 1 month. Forecasts whose 12-month target runs past "
                            "2025-03 have no outcome and aren't scored."},
    "oilflows": {"blocks": md.OILFLOW_BLOCKS, "stem": "oilflows", "title": "Oil flows by country", "word": "Flow",
                 "words": "flows", "variants": ("global", "global_nooil"),
                 "groups": tuple(dict.fromkeys(g for *_, g, _ in md.JODI_FLOWS)),
                 "items": {g: [(f"{p}_{fl}", w[0].upper() + w[1:]) for _, p, fl, gg, w in md.JODI_FLOWS if gg == g]
                           for g in dict.fromkeys(g for *_, g, _ in md.JODI_FLOWS)},
                 "files": ("jodi_oil_kbd.csv",),
                 "sources": "the JODI Oil World database (Joint Organisations Data Initiative: monthly crude and oil "
                            "product flows reported by national administrations, thousand barrels a day; JODI marks many "
                            "values as not assessed)",
                 "coverage": f"Every flow is asked for in each of the {len(md.JODI_COUNTRIES)} JODI reporting areas; a "
                             f"series enters if it has {md.SECTOR_MIN_MONTHS}+ months from {md.START[:4]} and data after "
                             f"{md.SECTOR_LIVE_FROM[:7]} ({{skipped}} published series were too short or stopped; the rest "
                             "aren't published). A flow of 0 counts as missing, so an importer's crude exports drop out. "
                             "Publication lag: 2 months."},
    "markets": {"blocks": md.MARKET_BLOCKS, "stem": "markets", "title": "Commodity prices by kind", "word": "Kind",
                "words": "kinds", "variants": ("global", "global_nooil"), "groups": ("commodity",),
                "items": {"commodity": md.KINDS},
                "files": ("worldbank_cmo_monthly.xlsx", "fao_food_price_indices.csv"),
                "sources": "the World Bank Pink Sheet, IMF primary commodity prices and indices (via FRED), US refined "
                           "product spot prices (EIA via FRED) and the FAO food price indices",
                "coverage": f"A price enters if it has {md.SECTOR_MIN_MONTHS}+ months from {md.START[:4]} and data "
                            f"after {md.SECTOR_LIVE_FROM[:7]} ({{skipped}} were too short or stopped). Publication lags: "
                            "1 month, 0 for the EIA spot prices, which are daily."},
}
WHAT = {"price": "producer prices", "output": "output", "consumer": "consumer prices", "commodity": "world prices",
        "headline": "headline consumer prices", "energy": "energy consumer prices",
        "utilities": "housing and utilities consumer prices", "food": "food consumer prices", "producer": "producer prices"}
MIN_TRAIN = 60  # monthly changes a series needs in a fold's training months to be scored there
SCALE_MIN = 0.05  # report: outputs whose climatology CRPS is below this (pp) are left out, see report()
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


def dataset(spec: dict) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return mn.make_dataset(spec["blocks"])


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


def scored(nets: list, st, info: dict, data: dict, t: np.ndarray, future: np.ndarray, rng, Ys: np.ndarray,
           n: int) -> dict:
    """CRPS and the 5% and 95% quantiles of macro_global.simulate's draws, CHUNK origins at a time,
    so the draws of every origin are never held at once (each origin is summarised on its own)."""
    parts = [mb.summarise(mg.simulate(nets, st, info, data, t[i:i + CHUNK], future[:, i:i + CHUNK], rng, n=n),
                          Ys[i:i + CHUNK]) for i in range(0, len(t), CHUNK)]
    return {key: np.round(np.concatenate([np.asarray(p[key], float) for p in parts]), 4).tolist()
            for key in ("crps", "q05", "q95")}


def fold_setup(data: dict, j: int) -> tuple:
    """Training rows, scaling, series info and the scored test targets of fold j."""
    train, test, last = mb.fold_window(data, j)
    info, st = mb.series_info(data), stats(data, last)
    months, k, x, y = mg.training_rows(mg.features(data, st), last)
    n_train = np.isfinite(data["dM"][13:last + 1]).sum(0)
    ok = np.repeat(n_train >= MIN_TRAIN, len(mn.HORIZONS))  # per output, target-major as names
    return train, test, last, info, st, (months, k, x, y), ok, np.where(ok, data["Y"][test], np.nan)


def run_fold(data: dict, j: int, spec: dict) -> dict:
    dates, names = data["dates"], data["names"]
    train, test, last, info, st, (months, k, x, y), ok, Ys = fold_setup(data, j)
    print(f"fold {j}: train months to {last} ({len(y)} rows, {int(ok.sum()) // len(mn.HORIZONS)} of "
          f"{len(info['keys'])} series scored), test {dates[test[0]]:%Y-%m}..{dates[test[-1]]:%Y-%m}", flush=True)
    t, oil = data["t"][test], data["OIL"][test]
    shocked = oil.copy()
    shocked[:, 0] += mg.SHOCK
    draws = 50 if mg.QUICK else mb.DRAWS
    out = {"fold": j, "test_dates": [f"{d:%Y-%m}" for d in dates[test]], "names": names, "groups": data["groups"],
           "scored": ok.tolist(), "y": np.round(Ys, 4).tolist(), "train_months_to": int(last), "models": {}}
    for vi, variant in enumerate(spec["variants"]):
        t0 = time.time()
        xv = x.copy()
        if variant == "global_nooil":
            xv[:, OIL] = 0.0
        fitted = [mg.train(xv, k, y, months, info["floor"], variant == "global_lin", seed=1000 * j + 100 * vi + s)
                  for s in range(2 if mg.QUICK else mg.SEEDS)]
        nets = [NoOil(f[0]) if variant == "global_nooil" else f[0] for f in fitted]
        res = scored(nets, st, info, data, t, oil[None], np.random.default_rng(300 + j), Ys, draws)
        base = simulate(nets, st, info, data, t, oil[None], None, n=len(nets), noise=False)
        up = simulate(nets, st, info, data, t, shocked[None], None, n=len(nets), noise=False)
        out["models"][variant] = res | {"training": [f[1] for f in fitted], "seconds": round(time.time() - t0, 1),
                                        "response_up10": np.round((up - base).mean((0, 1)), 4).tolist()}
        print(f"  {variant}: best epochs {[f[1]['best_epoch'] for f in fitted]}, CRPS {np.nanmean(res['crps']):.4f} "
              f"({time.time() - t0:.0f}s)", flush=True)
    out["models"]["ols"] = scored([mg.OLS(x, k, y, info["floor"])], st, info, data, t, oil[None],
                                  np.random.default_rng(500 + j), Ys, draws)
    with warnings.catch_warnings():  # a price that never moved in training (sd 0) leaves its CRPS unscored (nan)
        warnings.simplefilter("ignore", RuntimeWarning)
        mu, sd = np.nanmean(data["Y"][train], 0), np.nanstd(data["Y"][train], 0)
        crps = np.where(np.isfinite(Ys), mb.gaussian_crps(mu, sd, np.nan_to_num(Ys)), np.nan)
    z = 1.6448536269514722  # 90% central interval of a Gaussian
    out["models"]["climatology"] = {key: np.round(np.broadcast_to(v, Ys.shape), 4).tolist() for key, v in
                                    (("crps", crps), ("q05", mu - z * sd), ("q95", mu + z * sd))}
    print(f"  ols CRPS {np.nanmean(out['models']['ols']['crps']):.4f}, climatology {np.nanmean(crps):.4f}", flush=True)
    return out


def run_benchmarks(data: dict) -> dict:
    """The small OLS on every fold, scored on the same outputs as run_fold (no training loop)."""
    folds = []
    for j in range(mn.FOLDS):
        _, test, _, info, st, (months, k, x, y), _, Ys = fold_setup(data, j)
        res = scored([SmallOLS(x, k, y, info["floor"])], st, info, data, data["t"][test], data["OIL"][test][None],
                     np.random.default_rng(700 + j), Ys, mb.DRAWS)
        folds.append({"fold": j, "test_dates": [f"{d:%Y-%m}" for d in data["dates"][test]]} | res)
        print(f"ols_small fold {j}: CRPS {np.nanmean(res['crps']):.4f}", flush=True)
    return {"folds": folds}


# --- report ----------------------------------------------------------------------------------

def report(spec: dict) -> None:
    warnings.simplefilter("ignore", RuntimeWarning)  # nan-means over outputs no fold scored
    stem, variants, groups_shown = spec["stem"], spec["variants"], spec["groups"]
    folds = [f for j in range(mn.FOLDS) if (f := mb.load(f"{stem}-fold-{j}.json"))]
    if not folds:
        raise SystemExit(f"no runs/macro/{stem}-fold-*.json yet")
    names = folds[0]["names"]
    for f in folds:
        assert f["names"] == names, f"{stem}-fold-{f['fold']}: outputs differ"
    keys = [n.split("@")[0] for n in names[::len(mn.HORIZONS)]]
    groups = np.array(folds[0]["groups"])
    H = np.array([int(n.split("@")[1]) for n in names])
    out_key = np.array([n.split("@")[0] for n in names])
    reg = {s.key: s for s in md.registry(md.ALL_BLOCKS)}
    item = np.array([reg[k].item for k in out_key])
    geo = np.array([reg[k].geo for k in out_key])
    countries = {"US": "United States"} | md.HOUSEHOLD_COUNTRIES | md.NATIONS

    def stack(get):
        return np.vstack([np.array(get(f), float) for f in folds])

    for f in folds:
        f["models"] = {m: f["models"][m] for m in (*variants, "ols", "climatology")}
    bench = mb.load(f"{stem}-benchmarks.json")
    bench = {b["fold"]: b for b in bench["folds"]} if bench else {}
    if all(f["fold"] in bench for f in folds):
        for f in folds:
            assert bench[f["fold"]]["test_dates"] == f["test_dates"], f"{stem}-benchmarks fold {f['fold']}: origins differ"
            f["models"]["ols_small"] = bench[f["fold"]]
    models = [m for m in (*variants, "ols", "ols_small", "climatology") if m in folds[0]["models"]]
    C = {m: stack(lambda f, m=m: f["models"][m]["crps"]) for m in models}
    scale = np.nanmean(C["climatology"], 0)
    # A price that practically never moved in training (Albania's rail fares) has a climatology CRPS
    # near 0, so any model's ratio to it explodes (to 60+) and swamps a group mean of hundreds.
    tiny = np.isfinite(scale) & (scale < SCALE_MIN)
    scale = np.where(tiny, np.nan, scale)
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
        for field, values in (("group", groups), ("item", item), ("geo", geo), ("key", out_key)):
            if field in kw:
                ok &= values == kw[field]
        if kw.get("h", "all") != "all":
            ok &= H == kw["h"]
        return np.flatnonzero(ok)

    def n_series(c):
        return len({out_key[i] for i in c if np.isfinite(scale[i])})

    first, last = folds[0]["test_dates"][0], folds[-1]["test_dates"][-1]
    n_orig = sum(len(f["test_dates"]) for f in folds)
    scored_keys = [k for k in keys if np.isfinite(scale[names.index(f"{k}@1")])]
    cnt = {g: sum(reg[k].target == g for k in scored_keys) for g in groups_shown}
    places = sorted({reg[k].geo for k in scored_keys if reg[k].geo})
    rows = [f["models"]["global"]["training"][0]["rows"] for f in folds]
    when = sorted(f["meta"]["generated"] for f in folds if "meta" in f)
    out = [
        f"# {spec['title']}: global network results", "",
        f"_Generated by `experiments/sector_global.py report --set {[s for s, v in SETS.items() if v is spec][0]}` on "
        f"{datetime.now(UTC).date().isoformat()} from {len(folds)} forward-chaining folds ({first}..{last}, {n_orig} "
        "forecast origins), the folds of `notes/macro-global-results.md`. Fold files generated "
        + (f"{when[0]} to {when[-1]}" if when else "(no timestamps)")
        + f". Data: {spec['sources']}, fetched by `experiments/macro_data.py`; real and revised (not real-time "
        "vintages); nothing is synthetic. Every forecast here is a **what-if**: it is given the oil path that "
        "happened._", "",
        "**Series scored:** " + ", ".join(f"{cnt[g]} {WHAT[g]}" for g in groups_shown)
        + f" ({len(places)} countries). One network is shared by all of them; training rows per fold run from "
        f"{rows[0]:,} to {rows[-1]:,} (the macro run had 1,682 to 5,818). A series is scored in a fold only if it "
        f"has {MIN_TRAIN}+ monthly changes in that fold's training months"
        + (f", and outputs whose climatology CRPS is below {SCALE_MIN} pp (a price that practically never moved, "
           f"where any ratio to it is meaningless) are left out: {', '.join(f'`{n}`' for n in np.array(names)[tiny])}"
           if tiny.any() else "") + ".", "",
        "Skill = 1 − CRPS / CRPS of climatology (each output's training mean and spread), averaged over the "
        "outputs in the row; 0 is no better than climatology. `global, no oil` is the same network with its "
        "oil inputs set to 0, so `global` minus `global, no oil` is what knowing oil adds. `OLS, same inputs` "
        "is per-series least squares on all 26 network inputs; `OLS, small` uses 4 of them (own last change, "
        "Brent lags 0–2), which is all 80–280 months per series can support.", ""]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        _, _, prov = md.build_panel(spec["blocks"])  # from the cache in data/raw/macro/
    kept = {p["series"].key: p for p in prov if "error" not in p and p["series"].block in md.GENERATED}
    n_skipped = sum(p["error"].startswith("skipped") for p in prov if "error" in p)
    files = [*(f for pattern in spec["files"] for f in md.RAW.glob(pattern)),
             *(md.RAW / f"fred_{s.code}.csv" for s in reg.values() if s.block in spec["blocks"][1:] and s.source == "fred")]
    fetched = sorted({datetime.fromtimestamp(f.stat().st_mtime, UTC).date().isoformat() for f in files if f.exists()})
    by_item = [g for g in groups_shown if g in spec["items"]]
    out += ["## Data", "",
            f"Fetched {fetched[0]}" + (f" to {fetched[-1]}" if fetched[-1] != fetched[0] else "") + ". "
            + (spec["coverage"].format(skipped=n_skipped) if "coverage" in spec else
               f"Every {spec['word'].lower()} is asked for in every European country Eurostat covers (and the US where "
               f"listed); a series enters if it has {md.SECTOR_MIN_MONTHS}+ months from {md.START[:4]} and data after "
               f"{md.SECTOR_LIVE_FROM[:7]} ({n_skipped} published series were too short or stopped; the rest aren't "
               "published). Publication lags: 2 months for Eurostat's producer prices and output, 1 for consumer "
               "prices, FRED and the World Bank. US sector series are the closest NAICS industries, not exact matches."),
            "",
            f"| {spec['word']} | Code | " + " | ".join(f"{WHAT[g].capitalize()}: series" for g in by_item)
            + " | Median first month (panel starts 2000-01) | Latest month |",
            "|---|---|" + "---|" * len(by_item) + "---|---|"]
    seen_items = []
    for g in by_item:
        seen_items += [i for i in spec["items"][g] if i not in seen_items]
    for code, name, *_ in seen_items:
        ps = [p for k, p in kept.items() if reg[k].item == code and reg[k].target in by_item]
        if not ps:
            continue
        n = {g: sum(p["series"].target == g for p in ps) for g in by_item}
        starts = sorted(max(p["first"], pd.Timestamp(md.START)) for p in ps)
        out.append(f"| {name} | {code} | " + " | ".join(str(n[g]) for g in by_item)
                   + f" | {starts[len(starts) // 2]:%Y-%m} | {max(p['last'] for p in ps):%Y-%m} |")
    out.append("")

    shown = [m for m in models if m != "climatology"]
    out += ["## Skill by horizon", "", "| Target | h | " + " | ".join(labels[m] for m in shown) + " |",
            "|---|---|" + "---|" * len(shown)]
    for grp in groups_shown:
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
    for grp in groups_shown:
        cells = []
        for m in shown:
            r = ratios(m, cols(group=grp))
            cells.append(f"{1 - np.nanmean(r):+.3f} / {1 - np.nanmedian(r):+.3f} / {np.mean(r[np.isfinite(r)] < 1):.0%}")
        out.append(f"| {grp} | " + " | ".join(cells) + " |")

    def row(label, c, n=True) -> str:
        return (f"| {label} | " + (f"{n_series(c)} | " if n else "") + " | ".join(f"{skill(m, c):+.3f}" for m in shown)
                + f" | {skill('global', c) - skill('global_nooil', c):+.3f} |")

    head = " | ".join(labels[m] for m in shown)
    for grp in by_item:
        out += ["", f"## {WHAT[grp].capitalize()} by {spec['word'].lower()} (all horizons)", "",
                f"| {spec['word']} | Series | {head} | oil adds |", "|---|---|" + "---|" * (len(shown) + 1)]
        out += [row(f"{name} ({code})", c) for code, name, *_ in spec["items"][grp]
                if n_series(c := cols(group=grp, item=code))]
    for grp in by_item:
        lines = [row(name, c) for code, name in countries.items() if n_series(c := cols(group=grp, geo=code))]
        if lines:
            out += ["", f"## {WHAT[grp].capitalize()} by country (all {spec['words']}, all horizons)", "",
                    f"| Country | Series | {head} | oil adds |", "|---|---|" + "---|" * (len(shown) + 1), *lines]

    # Breakdowns: the series grouped by their country's World Bank region and income group and its
    # oil trade position (JODI), and the forecast origins by whether their 12 months overlap a crisis.
    classes, position = md.country_classes(), md.oil_trade_position()
    code3 = {g: md.iso3(g, classes) for g in set(geo) if g}
    facets = [("World Bank region", lambda c: classes.get(c, {}).get("region")),
              ("World Bank income group", lambda c: classes.get(c, {}).get("income")),
              ("Oil trade position (JODI imports minus exports of crude and products, 2015–2024 average)",
               lambda c: position.get(c))]
    if any(geo):
        out += ["", "## Breakdowns by country group (all horizons)", "",
                "Each series counts in its country's group. Countries outside the World Bank's list (Taiwan) or "
                "without all four JODI trade flows are left out of that table.", ""]
        for title, fn in facets:
            cat = np.array([fn(code3.get(g)) if g else None for g in geo], dtype=object)
            out += [f"### {title}", "", f"| Target | Group | Series | {head} | oil adds |",
                    "|---|---|---|" + "---|" * (len(shown) + 1)]
            for grp in groups_shown:
                for value in sorted({v for v in cat[cols(group=grp)] if v}):
                    c = np.intersect1d(cols(group=grp), np.flatnonzero(cat == value))
                    if n_series(c):
                        out.append(row(f"{grp} | {value}", c))
            out.append("")
    origins = pd.to_datetime([d + "-01" for f in folds for d in f["test_dates"]])
    windows = [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in mn.CRISES]
    crisis = np.array([any(o + pd.DateOffset(months=1) <= b and o + pd.DateOffset(months=max(mn.HORIZONS)) >= a
                           for a, b in windows) for o in origins])

    def sub(m, c, rows):
        c = c[np.isfinite(scale[c]) & (scale[c] > 0)]
        return 1 - np.nanmean(np.nanmean(C[m][rows][:, c], 0) / scale[c]) if len(c) else np.nan

    out += ["", "## Crisis and calm forecast origins (all horizons)", "",
            "An origin is a crisis origin if its next 12 months overlap "
            + ", ".join(f"{a[:7]}..{b[:7]}" for a, b in mn.CRISES) + " (`macro_nn.CRISES`). Skill is against the "
            "same full-sample climatology yardstick.", "",
            f"| Target | Origins | Count | {head} | oil adds |", "|---|---|---|" + "---|" * (len(shown) + 1)]
    for grp in groups_shown:
        for label, rows_ in (("crisis", crisis), ("calm", ~crisis)):
            c = cols(group=grp)
            out.append(f"| {grp} | {label} | {int(rows_.sum())} | " + " | ".join(f"{sub(m, c, rows_):+.3f}" for m in shown)
                       + f" | {sub('global', c, rows_) - sub('global_nooil', c, rows_):+.3f} |")
    if "commodity" in groups_shown:
        out += ["", "## World prices (all horizons)", "", f"| Price | {head} | oil adds |",
                "|---|" + "---|" * (len(shown) + 1)]
        out += [row(reg[k].name, cols(key=k), n=False) for k in scored_keys if reg[k].target == "commodity"]

    best = "global_lin" if "global_lin" in variants else "global"
    per = sorted(((skill(best, cols(key=k)), k) for k in scored_keys if reg[k].target != "commodity"), reverse=True)
    out += ["", f"## Best and worst forecast series ({labels[best]}, all horizons)", "",
            "| | Series | Skill |", "|---|---|---|"]
    out += [f"| best {i + 1} | {reg[k].name} | {s:+.3f} |" for i, (s, k) in enumerate(per[:8])]
    out += [f"| worst {i + 1} | {reg[k].name} | {s:+.3f} |" for i, (s, k) in enumerate(per[::-1][:8])]

    y_all = stack(lambda f: f["y"])
    out += ["", "## Calibration: share of outcomes inside the central 90% interval (target 90%)", "",
            "| Target | " + " | ".join(labels[m] for m in models) + " |", "|---|" + "---|" * len(models)]
    for grp in groups_shown:
        c = cols(group=grp)
        c = c[np.isfinite(scale[c])]
        ok = np.isfinite(y_all[:, c])
        cells = []
        for m in models:
            lo, hi = stack(lambda f: f["models"][m]["q05"])[:, c], stack(lambda f: f["models"][m]["q95"])[:, c]
            cells.append(f"{np.mean(((y_all[:, c] >= lo) & (y_all[:, c] <= hi))[ok]):.0%}")
        out.append(f"| {grp} | " + " | ".join(cells) + " |")

    pairs = [(m, "climatology") for m in variants if m != "global_nooil"] + [("global", "ols")] \
        + ([("global", "ols_small")] if "ols_small" in models else []) \
        + ([("global_lin", "global")] if "global_lin" in variants else []) + [("global", "global_nooil")]
    out += ["", "## Are the differences real? Diebold–Mariano tests", "",
            "Mean difference in climatology-scaled CRPS over all horizons and the group's outputs (negative: the "
            "first model is better), with its Newey–West t-statistic (12 lags) over forecast origins. |t| > 2 is "
            "roughly significant at 5%.", "",
            "| Comparison | " + " | ".join(groups_shown) + " |", "|---|" + "---|" * len(groups_shown)]
    for m1, m2 in pairs:
        cells = []
        for grp in groups_shown:
            c = cols(group=grp)
            c = c[np.isfinite(scale[c]) & (scale[c] > 0)]
            d = np.nanmean((C[m1][:, c] - C[m2][:, c]) / scale[c], 1)
            d = d[np.isfinite(d)]
            cells.append(f"{np.mean(d):+.3f} (t {mb.nw_t(d):+.1f})")
        out.append(f"| {labels[m1]} vs {labels[m2]} | " + " | ".join(cells) + " |")

    out += ["", "## Did the networks train?", "",
            "Epoch with the lowest validation NLL (last quarter of the training months) per seed.", "",
            "| Fold | Training rows | " + " | ".join(f"{labels[m]}: best epochs" for m in variants) + " | Minutes |",
            "|---|---|" + "---|" * (len(variants) + 1)]
    for f in folds:
        tr = {m: f["models"][m]["training"] for m in variants}
        mins = sum(f["models"][m]["seconds"] for m in variants) / 60
        out.append(f"| {f['fold']} | {tr[variants[0]][0]['rows']:,} | "
                   + " | ".join(", ".join(str(s["best_epoch"]) for s in tr[m]) for m in variants) + f" | {mins:.0f} |")

    # mean over the folds where the output was scored (a series without training months has an untrained embedding)
    seen = stack(lambda f: f["scored"]).astype(bool)
    resp = [m for m in ("global_lin", "global") if m in variants]
    R = {m: np.nanmean(np.where(seen, stack(lambda f, m=m: f["models"][m]["response_up10"]), np.nan), 0) for m in resp}
    out += ["", "## Response to +10% Brent in the next month, 12 months on", "",
            "Location-only paths with and without the shock, on top of the oil path that happened, averaged over "
            f"each fold's test origins and networks, then over folds; in % of the level. For each {spec['word'].lower()}: "
            "the median over the countries that publish it, the middle 80% of countries, and the US.", "",
            f"| {spec['word']} | Target | Countries | {resp[0]} median | 10th–90th percentile | US |"
            + "".join(f" {m} median |" for m in resp[1:]), "|---|---|---|---|---|---|" + "---|" * len(resp[1:])]
    for grp in by_item:
        for code, name, *_ in spec["items"][grp]:
            ks = [k for k in scored_keys if reg[k].target == grp and reg[k].item == code]
            if not ks:
                continue
            r = {m: np.array([R[m][names.index(f"{k}@12")] for k in ks]) for m in resp}
            us = [k for k in ks if reg[k].geo in ("US", "USA")]
            us_r = f"{R[resp[0]][names.index(f'{us[0]}@12')]:+.1f}" if us else "–"
            lo, hi = np.percentile(r[resp[0]], [10, 90])
            out.append(f"| {name} ({code}) | {grp} | {len(ks)} | {np.median(r[resp[0]]):+.1f} | {lo:+.1f} to {hi:+.1f} | "
                       f"{us_r} |" + "".join(f" {np.median(r[m]):+.1f} |" for m in resp[1:]))
    for k in [k for k in scored_keys if reg[k].target == "commodity"]:
        c = names.index(f"{k}@12")
        out.append(f"| {reg[k].name} | commodity | | {R[resp[0]][c]:+.1f} | | |" + "".join(f" {R[m][c]:+.1f} |" for m in resp[1:]))
    path = NOTES / f"{stem}-global-results.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {path}")


# --- entry -----------------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("check", "fold", "benchmarks", "report"))
    p.add_argument("j", nargs="?", type=int, default=0)
    p.add_argument("--set", choices=SETS, default="sectors")
    a = p.parse_args()
    spec = SETS[a.set]
    if a.cmd == "report":
        return report(spec)
    data = dataset(spec)
    RUNS.mkdir(parents=True, exist_ok=True)
    if a.cmd == "benchmarks":
        path = RUNS / f"{spec['stem']}-benchmarks.json"
        path.write_text(json.dumps(run_benchmarks(data)))
        return print(f"wrote {path}")
    if a.cmd == "check":
        mg.QUICK = True
        out = run_fold(data, mn.FOLDS - 1, spec)
        print({m: float(np.nanmean(v["crps"])) for m, v in out["models"].items()})
        return
    meta = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "job": os.environ.get("SLURM_JOB_ID")}
    path = RUNS / f"{spec['stem']}-fold-{a.j}.json"
    path.write_text(json.dumps(run_fold(data, a.j, spec) | {"meta": meta}))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
