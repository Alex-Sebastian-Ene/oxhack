"""Report for experiments/cost_of_living.py: notes/cost-of-living.md and two CSVs for the UI.

Every skill is 1 - CRPS / CRPS of climatology (the training mean and spread of h-month changes),
averaged with equal weight over the series in a group; 0 is no better than climatology. Differences
between two forecasts are in units of each series' climatology CRPS, averaged over the series,
with a Newey-West error over forecast origins (lag = the horizon, since windows overlap).
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

import cost_of_living as col
import oil_chain as oc

KEYS = col.OUT_KEYS
KIND = {s.key: s.kind for s in col.SERIES} | {f"{r}_composite": "composite" for r in col.REGIONS}
REGION = {k: k.split("_")[0] for k in KEYS}
NAME = {s.key: s.name for s in col.SERIES} | {f"{r}_composite": f"{col.REGIONS[r]} composite (weighted items + rest)"
                                              for r in col.REGIONS}
ITEM_KINDS = [k for k in col.KINDS if k not in ("rest", "all")]
# Housing, core goods, other services and what is left of the rest, region by region, for the scenario
# and outlook tables.
CORE_BASKET = [s.key for r in col.REGIONS for s in col.SERIES
               if s.region == r and s.kind in ("housing", "core_goods", "services", "rest")]
H_IDX = {h: i for i, h in enumerate(col.HS)}
MODES = [("whatif", "Bayesian, given oil and gas"), ("whatif_no_regime", "same, no supply-shock terms"),
         ("avg_link", "average link (OLS)"), ("forecast_GARCH-CGMY", "forecast, Lévy Brent paths"),
         ("forecast_GARCH-Student-t", "forecast, Student-t Brent paths"), ("forecast_monthly-t", "forecast, monthly-t Brent paths")]


R_HAT_MAX, ESS_MIN = 1.05, 100  # the convergence bar of experiments/macro_bayes.py
# Institutional US CPI forecasts, scored by `experiments/macro_global.py benchmarks` on the chain's 8 folds
BENCH_FILE = col.ROOT / "runs" / "macro" / "global-benchmarks.json"
INSTITUTIONS = (("cleveland", "Cleveland Fed 1-year expected inflation (FRED EXPINF1YR)"),
                ("michigan", "Michigan 1-year expectations (FRED MICH)"),
                ("spf", "SPF median, at the end of each release month"),
                ("spf_mean", "SPF mean, at the end of each release month"),
                ("spf_latest", "SPF median, latest survey at every month-end"),
                ("rw", "Random walk: last 12-month pace carries on"))
BENCH_LAG = 12  # Newey-West lags of the comparison, as in the chain's Diebold-Mariano tests


def converged(d: dict) -> bool:
    return d["max_r_hat"] <= R_HAT_MAX and d["min_ess"] >= ESS_MIN and not d.get("quick")


def load_runs(folder=None) -> tuple[dict, dict]:
    """(converged fits, fits left out because their chains did not converge) in one runs folder."""
    folder = folder or col.RUNS_BASE
    ok, failed = {}, {}
    for n in col.NAMES:
        p = folder / f"{n}.json"
        if p.exists():
            r = json.loads(p.read_text())
            (ok if converged(r["diagnostics"]) and not r["meta"].get("quick") else failed)[n] = r
    return ok, failed


def stack(folds: list[dict], mode: str, field: str = "crps") -> np.ndarray:
    """[origins over all folds, len(HS), len(KEYS)] for a mode or a benchmark."""
    parts = []
    for f in folds:
        src = f["benchmarks"] if mode in f["benchmarks"] else f["modes"]
        parts.append(np.array(src[mode][field], float))
    return np.concatenate(parts)


def cols(keys: list[str]) -> np.ndarray:
    return np.array([KEYS.index(k) for k in keys])


def skill(m: np.ndarray, clim: np.ndarray, c: np.ndarray, hi=None) -> float:
    sl = slice(None) if hi is None else [hi]
    vals = [1 - np.nanmean(m[:, sl, k]) / np.nanmean(clim[:, sl, k]) for k in c]
    return float(np.nanmean(vals))


def diff(a: np.ndarray, b: np.ndarray, clim: np.ndarray, c: np.ndarray, hi: int) -> tuple[float, float]:
    """Mean of (a - b) / climatology CRPS over series c at horizon index hi, with a HAC error."""
    d = np.nanmean((a[:, hi, c] - b[:, hi, c]) / np.nanmean(clim[:, hi, c], 0), 1)
    d = d[np.isfinite(d)]
    b_, cov = oc.ols_hac(d, np.ones((len(d), 1)), col.HS[hi])
    return float(b_[0]), float(np.sqrt(cov[0, 0]))


def groups() -> list[tuple[str, list[str]]]:
    g = [(col.KIND_NAMES[k], [s.key for s in col.SERIES if s.kind == k]) for k in ITEM_KINDS]
    g += [("Rest of the basket (remainder)", [f"{r}_rest" for r in col.REGIONS])]
    g += [(f"{col.REGIONS[r]} headline: composite", [f"{r}_composite"]) for r in col.REGIONS]
    g += [(f"{col.REGIONS[r]} headline: direct", [f"{r}_all"]) for r in col.REGIONS]
    return g


def f2(v: float) -> str:
    return "-" if v is None or not np.isfinite(v) else f"{v:+.2f}"


def f3(v: float) -> str:
    return "-" if v is None or not np.isfinite(v) else f"{v:+.3f}"


def pct(v: float) -> str:
    return "-" if v is None or not np.isfinite(v) else f"{100 * v:.0f}%"


def fold_section(folds: list[dict]) -> list[str]:
    clim = stack(folds, "climatology")
    S = {m: stack(folds, m) for m, _ in MODES}
    I = {m: stack(folds, m, "inside90") for m, _ in MODES}
    n = len(clim)
    first, last = folds[0]["origins"][0], folds[-1]["origins"][-1]
    out = ["## Out of sample: 8 forward-chaining folds", "",
           f"{n} forecast origins, {first} to {last}. Each fold is fitted only on months before its block. "
           "*Given oil and gas* forecasts are told the Brent and gas path that happened (the what-if the app runs); "
           "*forecast* rows know nothing after the origin and simulate Brent from one of three models.", "",
           "**Skill against climatology, all horizons**", "",
           "| Group | " + " | ".join(lab for _, lab in MODES) + " |", "|---|" + "---|" * len(MODES)]
    for lab, keys in groups():
        c = cols(keys)
        out.append(f"| {lab} | " + " | ".join(f3(skill(S[m], clim, c)) for m, _ in MODES) + " |")
    out += ["", "**Share of outcomes inside the central 90% interval** (target 90%)", "",
            "| Group | " + " | ".join(lab for _, lab in MODES) + " |", "|---|" + "---|" * len(MODES)]
    for lab, keys in groups():
        c = cols(keys)
        out.append(f"| {lab} | " + " | ".join(pct(np.nanmean(I[m][:, :, c])) for m, _ in MODES) + " |")
    # the comparisons that decide what the model keeps
    out += ["", "**Does each feature earn its place?** Difference in CRPS (negative = the first is better), in units of "
            "climatology CRPS, ± Newey-West error.", "",
            "| Comparison | Series | " + " | ".join(f"h={h}" for h in col.HS) + " |", "|---|---|" + "---|" * len(col.HS)]
    item_keys = [s.key for s in col.SERIES if s.basket and s.kind not in ("rest", "all")]
    ind_keys = [s.key for s in col.SERIES if s.kind.startswith("ind_")]
    macro_keys = [s.key for s in col.SERIES if s.kind in ("unemployment", "rate")]
    tests = [("Bayesian vs average link (given oil and gas)", "whatif", "avg_link", item_keys, "all items"),
             ("Bayesian vs average link (given oil and gas)", "whatif", "avg_link", ind_keys, "US industry costs"),
             ("Bayesian vs average link (given oil and gas)", "whatif", "avg_link", macro_keys, "unemployment and rates"),
             ("Supply-shock terms on vs off", "whatif", "whatif_no_regime", ind_keys, "US industry costs"),
             ("Supply-shock terms on vs off", "whatif", "whatif_no_regime", item_keys, "all items"),
             ("Lévy vs Student-t Brent paths (forecast)", "forecast_GARCH-CGMY", "forecast_GARCH-Student-t", item_keys,
              "all items"),
             ("Lévy vs monthly-t Brent paths (forecast)", "forecast_GARCH-CGMY", "forecast_monthly-t", item_keys, "all items")]
    for r in col.REGIONS:
        tests.append((f"{col.REGIONS[r]}: composite vs direct headline (given oil and gas)", "whatif", None,
                      [f"{r}_composite", f"{r}_all"], "headline"))
    for lab, a, b, keys, what in tests:
        cells = []
        for h in col.HS:
            hi = H_IDX[h]
            if b is None:  # composite vs direct: same mode, two columns
                ca, cb = cols(keys[:1]), cols(keys[1:])
                d = (S[a][:, hi, ca[0]] - S[a][:, hi, cb[0]]) / np.nanmean(clim[:, hi, cb[0]])
                d = d[np.isfinite(d)]
                bb, cov = oc.ols_hac(d, np.ones((len(d), 1)), h)
                cells.append(f"{bb[0]:+.3f} ± {np.sqrt(cov[0, 0]):.3f}")
            else:
                m_, s_ = diff(S[a], S[b], clim, cols(keys), hi)
                cells.append(f"{m_:+.3f} ± {s_:.3f}")
        out.append(f"| {lab} | {what} | " + " | ".join(cells) + " |")
    # Brent drivers on their own
    out += ["", "**Brent itself: h-month change of the monthly average, forecast from each origin**", "",
            "| Brent paths | " + " | ".join(f"CRPS h={h}" for h in col.HS) + " | 90% coverage | vs Lévy, h=12 |",
            "|---|" + "---|" * (len(col.HS) + 2)]
    B = {d: np.concatenate([np.array(f["brent"][d]["crps"], float) for f in folds]) for d in
         ("GARCH-CGMY", "GARCH-Student-t", "monthly-t")}
    BI = {d: np.concatenate([np.array(f["brent"][d]["inside90"], float) for f in folds]) for d in B}
    names = {"GARCH-CGMY": "daily GARCH-CGMY (Lévy), stored yearly fits", "GARCH-Student-t": "daily GARCH-Student-t, stored yearly fits",
             "monthly-t": "monthly GARCH-t, refitted each origin"}
    for d in B:
        cr = [np.nanmean(B[d][:, H_IDX[h], 0]) for h in col.HS]
        if d == "GARCH-CGMY":
            vs = "-"
        else:
            dd = (B["GARCH-CGMY"][:, H_IDX[12], 0] - B[d][:, H_IDX[12], 0])
            dd = dd[np.isfinite(dd)]
            bb, cov = oc.ols_hac(dd, np.ones((len(dd), 1)), 12)
            vs = f"{bb[0]:+.2f} ± {np.sqrt(cov[0, 0]):.2f}"
        out.append(f"| {names[d]} | " + " | ".join(f"{v:.2f}" for v in cr) + f" | {pct(np.nanmean(BI[d]))} | {vs} |")
    out += ["", "CRPS of Brent in percentage points of log change. Negative in the last column means the Lévy paths "
            "scored better.", ""]
    diag = [f["diagnostics"] for f in folds]
    out += ["**Sampler health (folds):** " + "; ".join(
        f"fold {f['fold']}: R-hat {d['max_r_hat']}, ESS {d['min_ess']}, {d['divergences']} divergences, {d['seconds']:.0f} s"
        for f, d in zip(folds, diag)), ""]
    return out


def bench_by_origin(bench: dict, origins: list[str], key: str, h: int) -> np.ndarray:
    """A benchmark's US CPI CRPS at horizon h for each of our origins (NaN where it has none). The two
    sets of folds can differ by a month or two at their edges, so the match is by origin month."""
    by = {}
    for f in bench["folds"]:
        j = f["names"].index(f"us_cpi@{h}")
        for o, date in enumerate(f["test_dates"]):
            by[date] = f["crps"][key][o][j]
    return np.array([np.nan if by.get(d) is None else by[d] for d in origins], float)


def institutions_section(folds: list[dict], bench: dict) -> list[str]:
    mode = "forecast_GARCH-CGMY"
    origins = [o for f in folds for o in f["origins"]]
    clim, S, I = stack(folds, "climatology"), stack(folds, mode), stack(folds, mode, "inside90")
    ours = (("us_composite", "Our US composite (items + rest)"), ("us_all", "Our US headline, forecast directly"))
    B = {(k, h): bench_by_origin(bench, origins, k, h) for k, _ in INSTITUTIONS for h in col.HS}
    head = KEYS.index("us_all")  # one scale for every row: the climatology of US headline CPI
    gen = bench["meta"]["generated"][:10]
    out = ["## Against the Fed and the SPF: US CPI", "",
           f"_Benchmarks from `{BENCH_FILE.relative_to(col.ROOT).as_posix()}` (written by `experiments/macro_global.py "
           f"benchmarks` on {gen}; surveys fetched {bench['fetched']}, SPF to the {bench['spf_last_survey']} survey)._", "",
           "Our rows are the forecast mode with Lévy Brent paths: nothing after the origin is known. The benchmarks are the "
           "chain's, on the same 8 folds, matched by origin month. That gives us a head start: we start from the origin "
           "month's CPI, which is published about two weeks into the next month, while the Cleveland and Michigan values "
           "are taken at the end of the origin month, before it. It matters most at 1-3 months. Each benchmark is a "
           "point forecast with a Gaussian band of the "
           "spread of its own errors on the fold's training origins. Cleveland and Michigan give 1-year rates, scaled by "
           "h/12 at shorter horizons; the SPF's quarterly path is interpolated to months (`docs/macro-ensemble.md`). The "
           "surveys were made with the data as first published, while we train and score on today's revised CPI "
           "(`CPIAUCSL`, revised only through its seasonal factors), which flatters us slightly.", "",
           "**Skill against the climatology of US headline CPI**, each on the origins it has (the release-month SPF has "
           "one a quarter)", "",
           "| Forecast | " + " | ".join(f"h={h}" for h in col.HS) + " |", "|---|" + "---|" * len(col.HS)]
    for k, lab in ours:
        c = KEYS.index(k)
        out.append(f"| {lab} | " + " | ".join(f3(1 - np.nanmean(S[:, H_IDX[h], c]) / np.nanmean(clim[:, H_IDX[h], head]))
                                              for h in col.HS) + " |")
    for k, lab in INSTITUTIONS:
        cells = []
        for h in col.HS:
            b, cl = B[(k, h)], clim[:, H_IDX[h], head]
            ok = np.isfinite(b) & np.isfinite(cl)
            cells.append(f3(1 - b[ok].mean() / cl[ok].mean()))
        out.append(f"| {lab} | " + " | ".join(cells) + " |")
    out += ["| 90% coverage of our US composite | " + " | ".join(
        pct(np.nanmean(I[:, H_IDX[h], KEYS.index("us_composite")])) for h in col.HS) + " |", ""]
    for k, lab in ours:
        c = KEYS.index(k)
        out += [f"**{lab} against each benchmark**: how much lower our CRPS is, on the origins both have; t is the "
                f"Diebold-Mariano statistic of ours minus theirs (Newey-West, {BENCH_LAG} lags; negative = ours better)", "",
                "| Benchmark | " + " | ".join(f"h={h}" for h in col.HS) + " |", "|---|" + "---|" * len(col.HS)]
        for bk, blab in INSTITUTIONS:
            cells = []
            for h in col.HS:
                a, b, cl = S[:, H_IDX[h], c], B[(bk, h)], clim[:, H_IDX[h], head]
                ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(cl)
                d = (a[ok] - b[ok]) / cl[ok].mean()
                m_, cov = oc.ols_hac(d, np.ones((len(d), 1)), BENCH_LAG)
                lower = 1 - a[ok].mean() / b[ok].mean()
                cells.append(f"{abs(100 * lower):.0f}% {'lower' if lower >= 0 else 'higher'} "
                             f"(t {m_[0] / np.sqrt(cov[0, 0]):+.1f}, n {ok.sum()})")
            out.append(f"| {blab} | " + " | ".join(cells) + " |")
        out.append("")
    return out


def event_test(ev: dict, label: str) -> list[str]:
    """The fan given the oil and gas that happened, against the actual, at the last known month."""
    n = ev["actual_months"]
    hi = n - 1
    act = np.array(ev["actual"], float)[hi]
    out = [f"## {label}: fitted to {ev['base'][:7]}, scored {n} months on", "",
           f"Supply-disruption months in the fit: {ev['diagnostics']['supply_months']}. Each cell is the median "
           "change since the base month and its 90% interval, in % of the price level; ✓ marks an actual inside it.", "",
           "| Series | Weight | Actual | Bayesian, supply-shock terms | Bayesian, no supply-shock terms | Average link |",
           "|---|---|---|---|---|---|"]
    w = ev.get("weights") or {}
    models = ("whatif", "whatif_no_regime", "avg_link")
    basket = {s.key for s in col.SERIES if s.basket} | {f"{r}_composite" for r in col.REGIONS}
    hits = {g: {m: [] for m in models} for g in ("basket", "other")}
    err = {g: {m: [] for m in models} for g in ("basket", "other")}
    for k, key in enumerate(KEYS):
        a = act[k]
        if a <= -998:
            continue
        g = "basket" if key in basket else "other"
        cells = []
        for m in models:
            f = ev["fans"][m]
            lo, mid, hi_ = f["q05"][hi][k], f["q50"][hi][k], f["q95"][hi][k]
            inside = lo <= a <= hi_
            hits[g][m].append(inside)
            err[g][m].append(abs(mid - a))
            cells.append(f"{mid:+.1f} ({lo:+.1f} to {hi_:+.1f}){' ✓' if inside else ''}")
        out.append(f"| {NAME[key]} | {w.get(key, '') if w.get(key) is None else f'{100 * w[key]:.1f}%'} | {a:+.1f} | "
                   + " | ".join(cells) + " |")
    out += ["", "| | Bayesian, supply-shock terms | Bayesian, no supply-shock terms | Average link |", "|---|---|---|---|"]
    for g, lab in (("basket", "basket items, rest, headline and composites"),
                   ("other", "industry costs, unemployment and rates")):
        if hits[g]["whatif"]:
            out += [f"| Actuals inside the 90% interval, {lab} | " + " | ".join(
                        f"{sum(hits[g][m])}/{len(hits[g][m])}" for m in models) + " |",
                    f"| Mean absolute miss of the median, {lab} (pp) | " + " | ".join(
                        f"{np.mean(err[g][m]):.2f}" for m in models) + " |"]
    return out + [""]


def multipliers_section(fin: dict, ev: dict | None = None) -> tuple[list[str], list[list]]:
    """The supply-disruption multiplier for every metric: how much more of an energy-cost move passes
    through in a disruption month (1 + kappa), pooled by kind and for each series. With ev (the 2026
    event fit, to Feb 2026) a second column gives the multiplier learned from 2022's months alone.
    Each row ends with that column's median and interval (blank without ev)."""
    kq, ks = fin["mu_kappa"], fin["kappa"]
    clear = lambda lo, hi: "clearly above 1" if lo > 1 else ("clearly below 1" if hi < 1 else "within noise")  # noqa: E731
    band = lambda q, i: tuple(1 + q[p][i] for p in ("q05", "q50", "q95"))  # noqa: E731
    cell = lambda lo, mid, hi: f"×{mid:.2f} ({lo:.2f} to {hi:.2f})"  # noqa: E731
    early = f" | From 2022 only (fit to {ev['diagnostics']['last']})" if ev else ""
    out = ["## Supply-disruption multiplier for every metric", "",
           f"In a supply-disruption month each series' energy-cost pass-through is multiplied by 1 + kappa. These are the "
           f"fitted multipliers from the all-data fit ({fin['diagnostics']['supply_months']} disruption months, 2022 and "
           f"2026), median and 90% interval. Pooled is the kind's mean across regions; a series' own value is shrunk "
           f"towards it."
           + (f" The last column is the 2026 test's fit, which has only 2022's {ev['diagnostics']['supply_months']} "
              "disruption months to learn from: what a model would have carried into the 2026 closure." if ev else ""),
           "", f"| Kind | Pooled multiplier | Reading{early} |", "|---|---|---|" + ("---|" if ev else "")]
    for i, k in enumerate(col.KINDS):
        lo, mid, hi = band(kq, i)
        out.append(f"| {col.KIND_NAMES[k]} | {cell(lo, mid, hi)} | {clear(lo, hi)}"
                   + (f" | {cell(*band(ev['mu_kappa'], i))}" if ev else "") + " |")
    out += ["", f"| Series | Multiplier | Reading | 12-month response to +10% Brent, normal → disruption{early} |",
            "|---|---|---|---|" + ("---|" if ev else "")]
    rn, rs = fin["response_10pct"]["normal"], fin["response_10pct"]["supply"]
    rows = []
    for j, s in enumerate(col.SERIES):
        lo, mid, hi = band(ks, j)
        e = band(ev["kappa"], j) if ev else None
        k = KEYS.index(s.key)
        unit = "pp" if s.transform == "diff" else "%"
        out.append(f"| {s.name} | {cell(lo, mid, hi)} | {clear(lo, hi)} | {rn['q50'][11][k]:+.2f} → "
                   f"{rs['q50'][11][k]:+.2f} {unit}" + (f" | {cell(*e)}" if ev else "") + " |")
        rows.append([s.key, s.region, s.kind, round(mid, 3), round(lo, 3), round(hi, 3), round(rn["q50"][11][k], 4),
                     round(rs["q50"][11][k], 4), unit] + ([round(e[1], 3), round(e[0], 3), round(e[2], 3)] if ev else ["", "", ""]))
    for r in col.REGIONS:
        k = KEYS.index(f"{r}_composite")
        a, b = rn["q50"][11][k], rs["q50"][11][k]
        out.append(f"| {NAME[f'{r}_composite']} | ×{b / a:.2f} (ratio of medians) | | {a:+.2f} → {b:+.2f} %"
                   + (" | |" if ev else " |"))
        rows.append([f"{r}_composite", r, "composite", round(b / a, 3), "", "", round(a, 4), round(b, 4), "%", "", "", ""])
    return out + [""], rows


def scenario_section(ev: dict, weights: dict) -> list[str]:
    show = [f"{r}_composite" for r in col.REGIONS] + [f"{r}_{i}" for r in col.REGIONS for i in ("fuel", "electricity", "gas")]
    show += [f"{r}_bread" for r in col.REGIONS] + [f"{r}_restaurants" for r in col.REGIONS] + CORE_BASKET
    out = ["## Scenario fans from February 2026: how much a closure moves and widens the band", "",
           "Brent paths from the daily GARCH-CGMY (Lévy) model, plus the 2026 closure's monthly Brent and gas moves scaled "
           "by severity (0 = no closure). The supply-shock terms are on in the closure scenarios. Median and 90% interval of the "
           "change since Feb 2026, % of the price level. Width = the interval's width, the band's volatility.", ""]
    for h in (6, 12):
        hi = h - 1
        out += [f"**{h} months ahead**", "", "| Series | No closure | 25% of 2026 | 50% of 2026 | As in 2026 | Width, none → as 2026 |",
                "|---|---|---|---|---|---|"]
        for key in show:
            k = KEYS.index(key)
            cells = []
            for sc in ("none", "closure_25", "closure_50", "closure_100"):
                f = ev["fans"][sc]
                cells.append(f"{f['q50'][hi][k]:+.1f} ({f['q05'][hi][k]:+.1f} to {f['q95'][hi][k]:+.1f})")
            w0 = ev["fans"]["none"]["q95"][hi][k] - ev["fans"]["none"]["q05"][hi][k]
            w1 = ev["fans"]["closure_100"]["q95"][hi][k] - ev["fans"]["closure_100"]["q05"][hi][k]
            out.append(f"| {NAME[key]} | " + " | ".join(cells) + f" | {w0:.1f} → {w1:.1f} |")
        fb = [ev["fans"][f"{sc}_brent"] for sc in ("none", "closure_25", "closure_50", "closure_100")]
        out.append("| Brent (log change, %) | " + " | ".join(f"{b['q50'][hi]:+.0f} ({b['q05'][hi]:+.0f} to {b['q95'][hi]:+.0f})"
                                                       for b in fb) + " | |")
        out.append("")
    return out


def final_section(fin: dict, weights: dict) -> list[str]:
    kq = fin["mu_kappa"]
    out = ["## Fitted on every month: extra pass-through in supply disruptions, and each item's share of the hit", "",
           f"Data to {fin['latest']}; supply-disruption months in the fit: {fin['diagnostics']['supply_months']}. "
           f"Sampler: R-hat {fin['diagnostics']['max_r_hat']}, ESS {fin['diagnostics']['min_ess']}, "
           f"{fin['diagnostics']['divergences']} divergences.", "",
           "**kappa by kind** (pooled across regions): the extra share of energy-cost pass-through in disruption months. "
           "0 = none; 1 = double. Median and 90% interval.", "", "| Kind | kappa |", "|---|---|"]
    for i, k in enumerate(col.KINDS):
        out.append(f"| {col.KIND_NAMES[k]} | {kq['q50'][i]:+.2f} ({kq['q05'][i]:+.2f} to {kq['q95'][i]:+.2f}) |")
    out += ["", "**Response to a sustained +10% Brent move, 12 months on** (% of the price level), and the item's weighted "
            "contribution to its region's composite (percentage points of headline).", "",
            "| Series | Weight | Normal months | Supply-disruption months | Contribution, normal | Contribution, disruption |",
            "|---|---|---|---|---|---|"]
    rn, rs = fin["response_10pct"]["normal"], fin["response_10pct"]["supply"]
    for k, key in enumerate(KEYS):
        w = weights.get(key)
        cn = f"{w * rn['q50'][11][k]:+.3f}" if w else ""
        cs = f"{w * rs['q50'][11][k]:+.3f}" if w else ""
        out.append(f"| {NAME[key]} | {'' if w is None else f'{100 * w:.1f}%'} | {rn['q50'][11][k]:+.2f} "
                   f"({rn['q05'][11][k]:+.2f} to {rn['q95'][11][k]:+.2f}) | {rs['q50'][11][k]:+.2f} "
                   f"({rs['q05'][11][k]:+.2f} to {rs['q95'][11][k]:+.2f}) | {cn} | {cs} |")
    o = fin["outlook"]
    out += ["", f"**Outlook from {fin['latest']}**, Lévy Brent paths, "
            f"{'the disruption assumed to continue' if fin['in_supply_regime'] else 'no disruption'}: change over the next 12 months.", "",
            "| Series | Median | 90% interval |", "|---|---|---|"]
    for key in ([f"{r}_composite" for r in col.REGIONS] + [f"{r}_{i}" for r in col.REGIONS for i in ("fuel", "electricity", "gas", "bread")]
                + CORE_BASKET):
        k = KEYS.index(key)
        out.append(f"| {NAME[key]} | {o['q50'][11][k]:+.1f} | {o['q05'][11][k]:+.1f} to {o['q95'][11][k]:+.1f} |")
    return out + [""]


def events_section(data: dict) -> list[str]:
    rows = col.event_table(data)
    out = ["## The miss: what each item did in the two supply shocks, against the average link", "",
           "Cumulative change from the base month (% of the price level). The average link is OLS on Brent (and gas) lags "
           "with month terms, fitted only on months up to the base, and given the oil and gas that happened.", ""]
    for label, a, b in col.EVENTS:
        rr = [r for r in rows if r["event"] == label]
        out += [f"**{label}**, {a[:7]} to {b[:7]}: Brent {rr[0]['brent']:+.0f}% (log)", "",
                "| Series | Weight | Actual | Average link, oil | Average link, oil and gas | Miss (actual − oil and gas) |",
                "|---|---|---|---|---|---|"]
        for r in rr:
            w = r["weight"]
            out.append(f"| {NAME.get(r['key'], r['key'])} | {'' if w is None or w == 1.0 else f'{100 * w:.1f}%'} | "
                       f"{r['actual']:+.1f} | {r['oil_only']:+.1f} | {r['oil_gas']:+.1f} | {r['actual'] - r['oil_gas']:+.1f} |")
        out.append("")
    fr = col.fuel_ratios()
    links = col.fuel_average_links()
    out += ["**Fuel against Brent in supply events** (FRED monthly averages; per +10% Brent in log terms)", "",
            "| Event | Months | Brent | US retail diesel | per +10% | Jet fuel, US Gulf | per +10% |", "|---|---|---|---|---|---|---|"]
    for r in fr:
        d = "-" if r["diesel_pct"] is None else f"{r['diesel_pct']:+.0f}%"
        dp = "-" if r["diesel_per10"] is None else f"{r['diesel_per10']:+.1f}"
        j = "-" if r["jet_pct"] is None else f"{r['jet_pct']:+.0f}%"
        jp = "-" if r["jet_per10"] is None else f"{r['jet_per10']:+.1f}"
        out.append(f"| {r['event']} | {r['from']} to {r['to']} | {r['brent_pct']:+.0f}% (${r['brent_from']:.0f} → "
                   f"${r['brent_to']:.0f}) | {d} | {dp} | {j} | {jp} |")
    out += ["", f"Average link for comparison (2000 onwards, oil lags 0–2): diesel {links['diesel']['per10']:+.1f} ± "
            f"{links['diesel']['se']:.1f}, jet {links['jet']['per10']:+.1f} ± {links['jet']['se']:.1f} per +10% Brent. "
            "Abqaiq lasted two weeks, so monthly averages hide it.", ""]
    return out


def data_section(data: dict) -> list[str]:
    w, yr = data["weights"]["w"], data["weights"]["year"]
    out = ["## Data", "",
           "| Series | Region | Source id | Weight in basket | Weight year | Data from | Data to | Fetched |", "|---|---|---|---|---|---|---|---|"]
    for s in col.SERIES:
        if s.source == "derived":
            first, last, fetched = "-", "-", "-"
        else:
            first, last = data["prov"].get(s.key, ("-", "-"))
            fetched = col.fetched(s)
        code = s.code.strip("/").split("/")[-2].upper() if s.source == "ons" else s.code
        wt = w.get(s.key)
        out.append(f"| {s.name} | {col.REGIONS[s.region]} | `{code}` | {'' if wt is None else f'{100 * wt:.2f}%'} | "
                   f"{yr.get(s.key, '')} | {first} | {last} | {fetched} |")
    for r in col.REGIONS:  # the services totals that other services are derived from (inputs, not modelled)
        s = col.SERVICES[r][0]
        first, last = data["prov"].get(s.key, ("-", "-"))
        code = s.code.strip("/").split("/")[-2].upper() if s.source == "ons" else s.code
        out.append(f"| {s.name}, input to other services | {col.REGIONS[r]} | `{code}` | {100 * w[s.key]:.2f}% | "
                   f"{yr.get(s.key, '')} | {first} | {last} | {col.fetched(s)} |")
    for k, (src, code, name) in col.DRIVERS.items():
        first, last = data["prov"][k]
        out.append(f"| {name} | driver | `{code}` | | | {first} | {last} | {col.fetched(col.Item(k, 'us', 'all', src, code, name, None, False, 0))} |")
    out += ["", f"Weights: US {col.US_WEIGHTS_SOURCE}; UK ONS CPI weights (series CJWB … CJYL, CJVC for rents, A9ER for "
            "non-energy industrial goods, ICVI for services); euro area Eurostat `prc_hicp_inw`, geo EA. Euro-area "
            "services and non-energy industrial goods come from Eurostat's COICOP 2018 dataset `prc_hicp_minr` (EA19), "
            "because the older dataset stops at 2025-12 and FRED doesn't carry them. Other services are each region's "
            "services total less the service items modelled on their own; the rest of the basket is headline minus every "
            "weighted item and other services, so the composite equals headline in every month by construction; it "
            "differs from a direct headline model only in its forecasts.", ""]
    return out


def write_csvs(runs: dict, data: dict) -> None:
    gen = datetime.now(UTC).date().isoformat()
    w = data["weights"]["w"]
    rows = []
    ev = runs.get("event-2026")
    if ev:
        act = np.array(ev["actual"], float)
        for sc in ("none", "closure_25", "closure_50", "closure_100", "whatif"):
            f = ev["fans"][sc]
            for k, key in enumerate(KEYS):
                for h in range(col.H):
                    a = act[h, k] if h < ev["actual_months"] and act[h, k] > -998 else ""
                    rows.append([ev["base"][:7], sc, key, REGION[key], KIND[key], h + 1] +
                                [round(f[q][h][k], 3) for q in ("q05", "q25", "q50", "q75", "q95")] + [a, w.get(key, ""), gen])
    fin = runs.get("final")
    if fin:
        f = fin["outlook"]
        for k, key in enumerate(KEYS):
            for h in range(col.H):
                rows.append([fin["latest"], "outlook", key, REGION[key], KIND[key], h + 1] +
                            [round(f[q][h][k], 3) for q in ("q05", "q25", "q50", "q75", "q95")] + ["", w.get(key, ""), gen])
    with open(col.NOTES / "cost-of-living-fans.csv", "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["origin", "scenario", "series", "region", "kind", "months_ahead", "q05", "q25", "q50", "q75", "q95",
                     "actual", "weight", "generated"])
        wr.writerows(rows)
    if fin:
        with open(col.NOTES / "cost-of-living-responses.csv", "w", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(["series", "region", "kind", "regime", "months_ahead", "q05", "q50", "q95", "weight",
                         "contribution_q50", "unit", "fitted_to", "generated"])
            for regime in ("normal", "supply"):
                r = fin["response_10pct"][regime]
                for k, key in enumerate(KEYS):
                    for h in range(col.H):
                        wt = w.get(key)
                        wr.writerow([key, REGION[key], KIND[key], regime, h + 1, round(r["q05"][h][k], 4),
                                     round(r["q50"][h][k], 4), round(r["q95"][h][k], 4), wt or "",
                                     round(wt * r["q50"][h][k], 5) if wt else "", "% of price level per sustained +10% Brent",
                                     fin["latest"], gen])


FOOD_ITEMS = [s.key for s in col.SERIES if s.kind in col.FOOD_KINDS and s.kind not in ("rest", "all")]
FOOD_GROUPS = [(col.KIND_NAMES[k], [s.key for s in col.SERIES if s.kind == k])
               for k in ("bread", "meat", "dairy", "oils_fats", "fruit_veg", "sugar", "restaurants")]
FOOD_GROUPS += [(f"{col.REGIONS[r]} cost of living (composite)", [f"{r}_composite"]) for r in col.REGIONS]


def food_section(base: dict, food: dict, data: dict) -> list[str]:
    """Do grain and urea prices help? The same fits with and without them, compared like for like."""
    out = ["## Rejected: grain and urea prices for every food series", "",
           "The same model and folds, refitted with the monthly change in grain prices (mean of wheat and maize, IMF) and "
           "in urea (World Bank) as extra drivers of the food items, restaurants, the rest of the basket and headline, "
           "lags 0–12. Both versions use 1,000 draws per chain and the same seeds; skill is against the base run's "
           "climatology for both.", ""]
    bf = [base.get(f"fold-{j}") for j in range(8)]
    ff = [food.get(f"fold-{j}") for j in range(8)]
    if all(bf) and all(ff):
        clim = stack(bf, "climatology")
        cols_ = {"base": {m: stack(bf, m) for m in ("whatif", "forecast_GARCH-CGMY")},
                 "food": {m: stack(ff, m) for m in ("whatif", "forecast_GARCH-CGMY")}}
        ins = {"base": stack(bf, "whatif", "inside90"), "food": stack(ff, "whatif", "inside90")}
        out += ["**Skill against climatology, all horizons, 8 folds**", "",
                "| Group | Base, given drivers | With food drivers | Base, forecast | With food drivers, forecast | "
                "90% coverage, base → food |", "|---|---|---|---|---|---|"]
        for lab, keys in FOOD_GROUPS:
            c = cols(keys)
            cells = [f3(skill(cols_[v][m], clim, c)) for m in ("whatif", "forecast_GARCH-CGMY") for v in ("base", "food")]
            cells = [cells[0], cells[1], cells[2], cells[3]]
            out.append(f"| {lab} | " + " | ".join(cells) + f" | {pct(np.nanmean(ins['base'][:, :, c]))} → "
                       f"{pct(np.nanmean(ins['food'][:, :, c]))} |")
        out += ["", "**With food drivers minus base**, CRPS in units of climatology CRPS (negative = food drivers better), "
                "± Newey–West error.", "", "| Series | Mode | " + " | ".join(f"h={h}" for h in col.HS) + " |",
                "|---|---|" + "---|" * len(col.HS)]
        rows = [("All food items", FOOD_ITEMS)] + [(f"{col.REGIONS[r]} composite", [f"{r}_composite"]) for r in col.REGIONS]
        for lab, keys in rows:
            for m, mlab in (("whatif", "given drivers"), ("forecast_GARCH-CGMY", "forecast")):
                cells = []
                for h in col.HS:
                    d, s = diff(cols_["food"][m], cols_["base"][m], clim, cols(keys), H_IDX[h])
                    cells.append(f"{d:+.3f} ± {s:.3f}")
                out.append(f"| {lab} | {mlab} | " + " | ".join(cells) + " |")
        out.append("")
    for name, label in (("event-2022", "2022"), ("event-2026", "2026")):
        if name not in base or name not in food:
            continue
        b, f = base[name], food[name]
        n = b["actual_months"]
        hi = n - 1
        act = np.array(b["actual"], float)[hi]
        keys = FOOD_ITEMS + [f"{r}_composite" for r in col.REGIONS]
        stats = {}
        for v, ev in (("base", b), ("food", f)):
            fan = ev["fans"]["whatif"]
            inside = [fan["q05"][hi][KEYS.index(k)] <= act[KEYS.index(k)] <= fan["q95"][hi][KEYS.index(k)] for k in keys]
            miss = [abs(fan["q50"][hi][KEYS.index(k)] - act[KEYS.index(k)]) for k in keys]
            stats[v] = (sum(inside), len(keys), float(np.mean(miss)))
        out += [f"**The {label} test** (fitted to {b['base'][:7]}, scored {n} months on, given the drivers that happened): "
                f"food items and composites inside their 90% bands {stats['base'][0]}/{stats['base'][1]} without food drivers, "
                f"{stats['food'][0]}/{stats['food'][1]} with them; mean miss of the median {stats['base'][2]:.2f} pp against "
                f"{stats['food'][2]:.2f} pp.", "",
                "| Series | Actual | Base (90%) | With food drivers (90%) |", "|---|---|---|---|"]
        for key in [f"{r}_{i}" for r in col.REGIONS for i in ("bread", "dairy", "oils_fats")] + [f"{r}_composite" for r in col.REGIONS]:
            k = KEYS.index(key)
            cells = []
            for ev in (b, f):
                fan = ev["fans"]["whatif"]
                lo, mid, hi_ = fan["q05"][hi][k], fan["q50"][hi][k], fan["q95"][hi][k]
                cells.append(f"{mid:+.1f} ({lo:+.1f} to {hi_:+.1f}){' ✓' if lo <= act[k] <= hi_ else ''}")
            out.append(f"| {NAME[key]} | {act[k]:+.1f} | " + " | ".join(cells) + " |")
        out.append("")
        con = f.get("contributions")
        if con:
            out += [f"**What moved food prices in {label}**: each driver's contribution to the change from {b['base'][:7]} to "
                    f"{n} months on (pp of the price level, posterior mean, food-driver model). *Other* is the actual minus all "
                    "drivers: drift, momentum from before, and everything the drivers don't capture.", "",
                    "| Series | Actual | Oil | Gas | Grain | Urea | Other |", "|---|---|---|---|---|---|---|"]
            for key in [f"{r}_{i}" for r in col.REGIONS for i in ("bread", "meat", "dairy", "oils_fats")] + \
                       [f"{r}_composite" for r in col.REGIONS]:
                k = KEYS.index(key)
                parts = [con[g][hi][k] for g in ("oil", "gas", "grain", "urea")]
                other = act[k] - con["all_drivers"][hi][k]
                out.append(f"| {NAME[key]} | {act[k]:+.1f} | " + " | ".join(f"{p:+.1f}" for p in parts) + f" | {other:+.1f} |")
            out.append("")
    fin = food.get("final")
    if fin and "grain" in fin["response_10pct"]:
        r = fin["response_10pct"]
        out += ["**Response to a sustained +10% move in each input, 12 months on** (food-driver model, all data, median and "
                "90% interval, % of the price level)", "",
                "| Series | +10% Brent | +10% grain prices | +10% urea |", "|---|---|---|---|"]
        for key in [f"{r_}_{i}" for r_ in col.REGIONS for i in ("bread", "meat", "dairy", "oils_fats")] + \
                   [f"{r_}_composite" for r_ in col.REGIONS]:
            k = KEYS.index(key)
            out.append(f"| {NAME[key]} | " + " | ".join(
                f"{r[g]['q50'][11][k]:+.2f} ({r[g]['q05'][11][k]:+.2f} to {r[g]['q95'][11][k]:+.2f})"
                for g in ("normal", "grain", "urea")) + " |")
        out.append("")
    return out


BREAD = [s.key for s in col.SERIES if s.kind == "bread"]


def bread_section(base: dict, bread: dict) -> list[str]:
    """The targeted version: grain prices for bread and cereals only, against the base model."""
    out = ["## Why the main model gives bread grain prices: against the oil-and-gas-only base", "",
           "Grain prices (mean of wheat and maize) as a driver of bread and cereals in all three regions, lags 0–12, with "
           "no urea and nothing else changed. The rule was fixed before this run on economic grounds (grain is the main "
           "input to bread), not chosen from the item results of the full version. Same folds, seeds and draws as the base "
           "model; skill against the base run's climatology. * marks a difference beyond 2 Newey–West errors.", ""]
    bf = [base.get(f"fold-{j}") for j in range(8)]
    tf = [bread.get(f"fold-{j}") for j in range(8)]
    if all(bf) and all(tf):
        clim = stack(bf, "climatology")
        rows = [("Bread and cereals, all regions", BREAD)] + [(NAME[k], [k]) for k in BREAD]
        rows += [(f"{col.REGIONS[r]} cost of living (composite)", [f"{r}_composite"]) for r in col.REGIONS]
        rows += [("All other food items", [k for k in FOOD_ITEMS if KIND[k] != "bread"])]
        for mode, mlab in (("whatif", "given the drivers that happened"), ("forecast_GARCH-CGMY", "true forecasts")):
            A, B = stack(tf, mode), stack(bf, mode)
            out += [f"**Bread-only version minus base, {mlab}** (negative = the bread-only version is better)", "",
                    "| Series | Skill, base | Skill, bread-only | " + " | ".join(f"h={h}" for h in col.HS) + " |",
                    "|---|---|---|" + "---|" * len(col.HS)]
            for lab, keys in rows:
                c = cols(keys)
                cells = []
                for h in col.HS:
                    d, s = diff(A, B, clim, c, H_IDX[h])
                    cells.append(f"{d:+.3f} ± {s:.3f}{' *' if abs(d) > 2 * s else ''}")
                out.append(f"| {lab} | {f3(skill(B, clim, c))} | {f3(skill(A, clim, c))} | " + " | ".join(cells) + " |")
            out.append("")
    for name, label in (("event-2022", "2022"), ("event-2026", "2026")):
        if name not in base or name not in bread:
            continue
        b, t = base[name], bread[name]
        hi = b["actual_months"] - 1
        act = np.array(b["actual"], float)[hi]
        out += [f"**The {label} test** (fitted to {b['base'][:7]}, scored {hi + 1} months on, given the drivers that happened)",
                "", "| Series | Actual | Base (90%) | Bread-only (90%) |", "|---|---|---|---|"]
        for key in BREAD + [f"{r}_composite" for r in col.REGIONS]:
            k = KEYS.index(key)
            cells = []
            for ev in (b, t):
                fan = ev["fans"]["whatif"]
                lo, mid, hi_ = fan["q05"][hi][k], fan["q50"][hi][k], fan["q95"][hi][k]
                cells.append(f"{mid:+.1f} ({lo:+.1f} to {hi_:+.1f}){' ✓' if lo <= act[k] <= hi_ else ''}")
            out.append(f"| {NAME[key]} | {act[k]:+.1f} | " + " | ".join(cells) + " |")
        out.append("")
    fin = bread.get("final")
    if fin and "grain" in fin["response_10pct"]:
        r = fin["response_10pct"]["grain"]
        out += ["**Response of bread and cereals to a sustained +10% move in grain prices, 12 months on** (bread-only "
                "version, all data, median and 90% interval, % of the price level): " + "; ".join(
                    f"{col.REGIONS[key.split('_')[0]]} {r['q50'][11][KEYS.index(key)]:+.2f} "
                    f"({r['q05'][11][KEYS.index(key)]:+.2f} to {r['q95'][11][KEYS.index(key)]:+.2f})" for key in BREAD) + ".", ""]
    return out


def write_contributions(food: dict) -> None:
    """notes/cost-of-living-contributions.csv: each driver's part in each event, for the UI."""
    rows = []
    gen = datetime.now(UTC).date().isoformat()
    for name in ("event-2022", "event-2026"):
        ev = food.get(name)
        if not ev or "contributions" not in ev:
            continue
        act = np.array(ev["actual"], float)
        con = ev["contributions"]
        for h in range(ev["actual_months"]):
            for k, key in enumerate(KEYS):
                if act[h, k] <= -998:
                    continue
                for g in ("oil", "gas", "grain", "urea"):
                    if g in con:
                        rows.append([ev["base"][:7], h + 1, key, REGION[key], KIND[key], g, round(con[g][h][k], 3),
                                     round(act[h, k], 3), gen])
    with open(col.NOTES / "cost-of-living-contributions.csv", "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["base_month", "months_after", "series", "region", "kind", "driver", "contribution_pp", "actual_pp",
                     "generated"])
        wr.writerows(rows)


def write() -> None:
    data = col.load()
    runs, failed = load_runs(col.RUNS_MAIN)  # the main model: oil and gas, plus grain for bread and cereals
    base_runs, base_failed = load_runs(col.RUNS_BASE)
    food_runs, food_failed = load_runs(col.RUNS_FOOD)
    folds = [runs[f"fold-{j}"] for j in range(8) if f"fold-{j}" in runs]
    today = datetime.now(UTC).date().isoformat()
    jobs = sorted({str(r["meta"].get("job")) for r in (runs | failed).values() if r["meta"].get("job")})
    fits = f"{len(runs)} converged fits" if runs else "no converged model fits yet (the event analysis needs none)"
    days = sorted({col.fetched(s) for s in col.SERIES + [col.SERVICES[r][0] for r in col.REGIONS]
                   if s.source != "derived"} - {"-"})
    fetched_on = days[0] if len(days) == 1 else f"{days[0]} to {days[-1]}" if days else "-"
    out = ["# Cost of living in an oil supply shock: the basket, item by item", "",
           f"_Generated by `experiments/cost_of_living.py report` on {today} from {fits} of the main model"
           f"{' (Iridis job ' + ', '.join(jobs) + ')' if jobs else ''}. Data fetched {fetched_on} (table below). The data are real; "
           "the only simulated inputs are Brent and gas paths in forecast and scenario rows._", "",
           "The main model gives every series oil and gas pass-through, and bread and cereals grain prices as well. It "
           "replaced the oil-and-gas-only base after beating it on the same folds; that comparison, and the grain-and-urea "
           "version that scored worse, are at the end.", "",
           "Method: `docs/cost-of-living.md`. Skill is 1 − CRPS / CRPS of climatology, with each series weighted equally "
           "in a group; 0 is no better than climatology.", ""]
    for lab, fl in (("", failed), (" (base runs)", base_failed), (" (grain-and-urea runs)", food_failed)):
        if fl:
            out += [f"**Left out{lab}, chains not converged** (needs R-hat ≤ {R_HAT_MAX} and ESS ≥ {ESS_MIN}): " + "; ".join(
                f"{n} (R-hat {r['diagnostics']['max_r_hat']}, ESS {r['diagnostics']['min_ess']})" for n, r in fl.items()), ""]
    if len(folds) < 8:
        folds = []  # the fold tables need every fold, or the comparison is not like for like
    out += events_section(data)
    if folds:
        out += fold_section(folds)
        if BENCH_FILE.exists():
            out += institutions_section(folds, json.loads(BENCH_FILE.read_text()))
    for name, label in (("event-2026", "The 2026 Hormuz closure as a test"), ("event-2022", "The 2022 shock as a test")):
        if name in runs:
            ev = runs[name] | {"weights": data["weights"]["w"]}
            out += event_test(ev, label)
    if "event-2026" in runs:
        out += scenario_section(runs["event-2026"], data["weights"]["w"])
    if "final" in runs:
        out += final_section(runs["final"], data["weights"]["w"])
        out += multipliers_section(runs["final"], runs.get("event-2026"))[0]
    if base_runs:
        out += bread_section(base_runs, runs)
    if base_runs and food_runs:
        out += food_section(base_runs, food_runs, data)
    out += data_section(data)
    (col.NOTES / "cost-of-living.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    write_csvs(runs, data)
    write_contributions(runs)
    if "final" in runs:
        ev = runs.get("event-2026")
        _, rows = multipliers_section(runs["final"], ev)
        with open(col.NOTES / "cost-of-living-multipliers.csv", "w", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(["series", "region", "kind", "multiplier_q50", "multiplier_q05", "multiplier_q95",
                         "response_normal_12m", "response_disruption_12m", "unit", "fitted_to", "generated",
                         "multiplier_2022only_q50", "multiplier_2022only_q05", "multiplier_2022only_q95", "fitted_to_2022only"])
            gen = datetime.now(UTC).date().isoformat()
            early = ev["diagnostics"]["last"] if ev else ""
            wr.writerows(r[:9] + [runs["final"]["latest"], gen] + r[9:] + [early if r[9] != "" else ""] for r in rows)
    print(f"wrote {col.NOTES / 'cost-of-living.md'} and the CSVs")
