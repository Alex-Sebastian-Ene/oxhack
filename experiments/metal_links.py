# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "xlrd>=2.0", "openpyxl>=3.1"]
# ///
"""Oil -> steel and oil -> aluminium price links (OXH-5), fitted like the validated industry links.

The link is macro_nn.Anchor's (oil_chain.py's distributed lag): the monthly log change of a price on
the current and lagged monthly log change of Brent (lags 0-12), monthly averages from 2000, with a
Newey-West error (lag 12) on the summed effect. It is checked on macro_nn's 8 forward-chaining
folds: fold j fits on every month before its test block (test origins 2008-01..2025-10, split in
8), and the link is validated in that fold if its summed effect clears 2 Newey-West errors.

The numbers shown come from the fit on all months, as in the OXH-3 table: the effect of a
sustained +10% Brent move (a one-off monthly log change of ln 1.10) after 3 and 12 months, i.e.
ln 1.10 times the sum of the first 3 or 12 lag coefficients. Two OXH-3 rows (plastics resin,
nitrogen fertiliser) are refitted here as a control.

    uv run experiments/metal_links.py   # notes/steel-aluminium-links.md, notes/steel-aluminium-responses.csv
"""

from __future__ import annotations

import csv
import hashlib
from datetime import UTC, datetime

import numpy as np
import pandas as pd

import macro_data as md
import oil_chain as oc

NOTE = md.ROOT / "notes" / "steel-aluminium-links.md"
TABLE = md.ROOT / "notes" / "steel-aluminium-responses.csv"
BRENT = "DCOILBRENTEU"
# FRED code -> (key, name). Codes and titles checked on the FRED series pages on 2026-10-24.
SERIES = {
    "WPU1017": ("ind_wpu1017", "US PPI steel mill products (BLS)"),
    "WPU1012": ("ind_wpu1012", "US PPI iron and steel scrap (BLS)"),
    "WPU102501": ("ind_wpu102501", "US PPI aluminum mill shapes (BLS)"),
    "PALUMUSDM": ("imf_palumusdm", "Global price of aluminum, $/t (IMF), world price check"),
}
# OXH-3 rows refitted as a control: (name, after 3 months, after 12 months, ± 12 months, folds).
CONTROLS = {
    "PCU325211325211": ("PPI plastics resin", 1.5, 2.3, 0.4, 8),
    "PCU325311325311": ("PPI nitrogen fertiliser", 1.7, 5.8, 1.5, 8),
}
LAGS, HAC_LAG, Z = 12, 12, 2.0  # macro_nn: 0-12 lags for materials, HAC lag max(lags, 6), ANCHOR_Z
SHOCK, SHOWN = np.log(1.10), (3, 12)
FOLDS, TEST_START, WINDOW, OIL_AHEAD = 8, "2008-01-01", 24, 12  # as in macro_nn.fold_indices
MIN_FOLDS = 6  # the weakest row the OXH-3 table still called validated cleared 6 of 8 folds
# Checks beside the method, not part of it: the 2008-09 crash left out; world demand held fixed
# (Kilian's index of global real economic activity, monthly change, lags 0-12); and the 2026 closure.
DEMAND, CRASH = "IGREA", ("2008-07-01", "2009-12-01")
CLOSURE = ("2025-09-01", "2026-09-01")  # fit to the first month, forecast to the second with real Brent


def load(codes) -> tuple[pd.DataFrame, dict]:
    """Monthly log levels (the demand index as is) on the macro panel's calendar, 2000-01 to Brent's last month."""
    raw = {c: md.fetch_fred(c) for c in codes}
    idx = pd.date_range(md.START, raw[BRENT].index.max(), freq="MS")
    info = {}
    for c, s in raw.items():
        path = md.RAW / f"fred_{c}.csv"
        info[c] = {"first": s.index.min(), "last": s.index.max(),
                   "missing": int(s.reindex(pd.date_range(md.START, s.index.max(), freq="MS")).isna().sum()),
                   "fetched": datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat(),
                   "md5": hashlib.md5(path.read_bytes()).hexdigest()}
    return pd.DataFrame({c: (s if c == DEMAND else np.log(s)).reindex(idx) for c, s in raw.items()}, index=idx), info


def fold_ends(idx: pd.DatetimeIndex) -> list[tuple[int, pd.Timestamp, pd.Timestamp]]:
    """macro_nn's folds on the same calendar: (last month fitted, first and last test origin)."""
    t = np.arange(WINDOW - 1, len(idx) - OIL_AHEAD)
    origins = idx[t]
    blocks = np.array_split(np.flatnonzero(origins >= TEST_START), FOLDS)
    # Anchor(data, t[train[-1]] + 12) with train = origins before test[0] - 12: the month before the block.
    return [(int(t[b[0]] - 1), origins[b[0]], origins[b[-1]]) for b in blocks]


def lagged(x: np.ndarray) -> np.ndarray:
    return np.column_stack([np.concatenate([np.full(lag, np.nan), x[:len(x) - lag]]) for lag in range(LAGS + 1)])


def fit(y: np.ndarray, oil: np.ndarray, last: int, control: np.ndarray | None = None, drop=None) -> dict:
    """y (100 x monthly log change) on oil lags 0..LAGS, months up to index `last`, as in Anchor.

    Sensitivity only: `control` adds lags 0..LAGS of another regressor; `drop` masks months out.
    """
    X = lagged(oil) if control is None else np.column_stack([lagged(oil), lagged(control)])
    ok = np.isfinite(y) & np.isfinite(X).all(1)
    ok[last + 1:] = False
    if drop is not None:
        ok &= ~drop
    b, cov = oc.ols_hac(y[ok], np.column_stack([np.ones(ok.sum()), X[ok]]), HAC_LAG)

    def summed(h):
        w = np.zeros(len(b))
        w[1:h + 1] = 1.0  # oil lags 0..h-1
        return float(w @ b), float(np.sqrt(w @ cov @ w))

    total, se = summed(LAGS + 1)
    return {"months": int(ok.sum()), "first": int(np.flatnonzero(ok)[0]), "last": int(np.flatnonzero(ok)[-1]),
            "total": total, "se": se, "clears": abs(total) > Z * se, "b": b,
            "after": {h: tuple(SHOCK * v for v in summed(h)) for h in SHOWN}}


def run(levels: pd.DataFrame, code: str) -> dict:
    oil, y = levels[BRENT].diff().values, 100 * levels[code].diff().values
    folds = [fit(y, oil, last) for last, _, _ in fold_ends(levels.index)]
    final = fit(y, oil, len(levels) - 1)
    hits = sum(f["clears"] for f in folds)
    return {"folds": folds, "final": final, "hits": hits,
            "validated": hits >= MIN_FOLDS and final["clears"]}


def sensitivity(levels: pd.DataFrame, code: str) -> dict:
    """All-data fit without the 2008-09 crash, and with world demand (Kilian's index) held fixed."""
    oil, y, last = levels[BRENT].diff().values, 100 * levels[code].diff().values, len(levels) - 1
    crash = (levels.index >= CRASH[0]) & (levels.index <= CRASH[1])
    return {"crash": fit(y, oil, last, drop=crash), "demand": fit(y, oil, last, control=levels[DEMAND].diff().values)}


def closure(levels: pd.DataFrame, code: str) -> dict:
    """Fit on months to CLOSURE[0], then feed the Brent path that happened over the next 12 months."""
    oil, y = levels[BRENT].diff().values, 100 * levels[code].diff().values
    t0, t1 = levels.index.get_loc(pd.Timestamp(CLOSURE[0])), levels.index.get_loc(pd.Timestamp(CLOSURE[1]))
    b = fit(y, oil, t0)["b"]
    oil_part = float(sum(lagged(oil)[t] @ b[1:] for t in range(t0 + 1, t1 + 1)))

    def pct(x):  # 100 x log change -> %
        return float(100 * np.expm1(x / 100))

    return {"actual": pct(100 * (levels[code].iloc[t1] - levels[code].iloc[t0])), "oil": pct(oil_part),
            "trend": pct(oil_part + b[0] * (t1 - t0))}


def main() -> None:
    codes = [BRENT, DEMAND, *SERIES, *CONTROLS]
    levels, info = load(codes)
    res = {c: run(levels, c) | {"sens": sensitivity(levels, c), "closure": closure(levels, c)}
           for c in [*SERIES, *CONTROLS]}
    ends = fold_ends(levels.index)
    write_table(levels, info, res)
    write_note(levels, info, res, ends)


def month(levels: pd.DataFrame, i: int) -> str:
    return f"{levels.index[i]:%Y-%m}"


def write_table(levels, info, res) -> None:
    generated = datetime.now(UTC).date().isoformat()
    rows = []
    for code, (key, name) in SERIES.items():
        r, f = res[code], res[code]["final"]
        source = (f"experiments/metal_links.py: FRED {code} ({name}; fetched {info[code]['fetched']}) on FRED "
                  f"{BRENT} (Brent, EIA; fetched {info[BRENT]['fetched']}); "
                  f"fit {month(levels, f['first'])}..{month(levels, f['last'])}")
        for h in SHOWN:
            mean, se = f["after"][h]
            rows.append({"series": key, "shock": "brent_up_10pct", "months_ahead": h, "mean": f"{mean:.4f}",
                         "q05": f"{mean - 1.645 * se:.4f}", "q95": f"{mean + 1.645 * se:.4f}",
                         "unit": "% of price level per sustained +10% Brent", "source": source,
                         "fitted_to": month(levels, f["last"]), "generated": generated,
                         "validated": "yes" if r["validated"] else "no", "folds_validated": f"{r['hits']}/{FOLDS}"})
    with TABLE.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def write_note(levels, info, res, ends) -> None:
    def cells(code):
        f = res[code]["final"]
        (m3, _), (m12, s12) = f["after"][3], f["after"][12]
        return f"{m3:+.2f} | **{m12:+.2f}** | {s12:.2f} | {res[code]['hits']}/{FOLDS}"

    out = [
        "# Oil → steel and oil → aluminium price links (OXH-5)",
        "",
        f"_Generated by `experiments/metal_links.py` on {datetime.now(UTC).date().isoformat()}. Every series is "
        "from FRED (St. Louis Fed), monthly averages; fetch dates and file hashes are in the data table below. "
        "Nothing here is synthetic._",
        "",
        "**Method.** The same link as the OXH-3 table and `macro_nn.Anchor`: the monthly log change of the "
        "price on the current and lagged monthly log change of Brent (lags 0–12), months from "
        f"{month(levels, res['WPU1017']['final']['first'])}, Newey–West errors (lag {HAC_LAG}) on the summed "
        f"effect. Checked on macro_nn's {FOLDS} forward-chaining folds, each fitted only on the months before "
        f"its test block (test years {ends[0][1]:%Y-%m}..{ends[-1][2]:%Y-%m}). A fold validates the link if its "
        f"summed effect (lags 0–{LAGS}) clears {Z:g} Newey–West errors there. The numbers shown come from the fit "
        "on all months.",
        "",
        "- **The shock:** a sustained +10% Brent move, i.e. the price stays 10% higher from next month on.",
        "- **After 3 / 12 months:** ln 1.10 times the sum of the first 3 / 12 lag coefficients, in % of the "
        "price level.",
        "- **±:** one Newey–West standard error. In the CSV, q05/q95 are the mean ± 1.645 errors: the "
        "uncertainty of the average effect, not the range of single outcomes (which is wider).",
        f"- **Validated:** the all-data fit clears {Z:g} errors and at least {MIN_FOLDS} of {FOLDS} folds do (the "
        f"weakest row the OXH-3 table called validated cleared {MIN_FOLDS}/{FOLDS}). Anything else is "
        "**not validated**.",
        "- **Other move sizes:** the link is linear in log terms, so scale by ln(1+x) / ln(1.10); a 10% fall "
        "gives the mirror image (rises and falls were not tested separately).",
        "",
        "## Result",
        "",
        "| Series | FRED | After 3 months | After 12 months | ± (12 m) | Validated in folds | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for code, (_, name) in SERIES.items():
        status = "**validated**" if res[code]["validated"] else "**not validated**"
        out.append(f"| {name} | `{code}` | {cells(code)} | {status} |")
    out += ["", f"CSV: `{TABLE.relative_to(md.ROOT).as_posix()}` (columns `series, shock, months_ahead, mean, q05, "
            "q95, unit, source, fitted_to, generated`, plus `validated` and `folds_validated`).", "",
            "## Fold by fold", "",
            f"Summed effect of lags 0–{LAGS} for a sustained +10% Brent move, ± one Newey–West error; **bold** "
            f"where it clears {Z:g} errors.", "",
            "| Fold | Fitted on | Test origins | " + " | ".join(SERIES) + " |",
            "|---|---|---|" + "---|" * len(SERIES)]
    def summed(f):
        v = f"{SHOCK * f['total']:+.2f} ± {SHOCK * f['se']:.2f}"
        return f"**{v}**" if f["clears"] else v

    for j, (last, t0, t1) in enumerate(ends):
        first = month(levels, res["WPU1017"]["folds"][j]["first"])
        out.append(f"| {j} | {first}..{month(levels, last)} | {t0:%Y-%m}..{t1:%Y-%m} | "
                   + " | ".join(summed(res[c]["folds"][j]) for c in SERIES) + " |")
    final = res["WPU1017"]["final"]
    out.append(f"| all | {month(levels, final['first'])}..{month(levels, final['last'])} | – | "
               + " | ".join(summed(res[c]["final"]) for c in SERIES) + " |")
    misses = [f"`{c}` fold{'s' if len(m) > 1 else ''} {', '.join(map(str, m))}" for c in SERIES
              if (m := [j for j, f in enumerate(res[c]["folds"]) if not f["clears"]])]
    out += ["", "Folds where the link does not clear: " + ("; ".join(misses) if misses else "none") + "."]
    out += ["", "## Control: OXH-3 rows refitted with this script", "",
            "Same code and the same cached Brent file as the OXH-3 run; the rows should match the OXH-3 table. "
            "On 2026-10-24 the fold fits were also checked against `macro_nn.Anchor` run on the same arrays: "
            "same months in every fold, largest gap in effect or error 1.4e-14.", "",
            "| Series | FRED | After 3 months | After 12 months | ± (12 m) | Validated in folds | OXH-3 table |",
            "|---|---|---|---|---|---|---|"]
    for code, (name, a3, a12, s12, k) in CONTROLS.items():
        out.append(f"| {name} | `{code}` | {cells(code)} | {a3:+.1f} / {a12:+.1f} ± {s12} / {k}/{FOLDS} |")

    def z(f):
        m, s = f["after"][12]
        return f"{m:+.2f} ± {s:.2f}" + (" (clears)" if f["clears"] else " (does not clear)")

    names = {BRENT: "Brent spot, $/bbl (EIA), daily → monthly mean",
             DEMAND: "Index of global real economic activity (Kilian), sensitivity only",
             **{c: n for c, (_, n) in SERIES.items()}, **{c: n for c, (n, *_) in CONTROLS.items()}}
    out += ["", "## Sensitivity: is it oil, or world demand?", "",
            "Metals and oil both follow world demand, and the method above cannot tell the two apart. Two "
            "checks on the all-data fit (effect after 12 months ± one error; \"clears\" is the summed effect of "
            f"lags 0–{LAGS} against {Z:g} errors). They are not part of the method, so they do not change the "
            "status above.", "",
            f"| Series | As fitted | Without {CRASH[0][:7]}..{CRASH[1][:7]} | World demand held fixed |",
            "|---|---|---|---|"]
    for code in [*SERIES, *CONTROLS]:
        s = res[code]["sens"]
        out.append(f"| {names[code]} | {z(res[code]['final'])} | {z(s['crash'])} | {z(s['demand'])} |")
    out += ["", f"\"World demand held fixed\" adds lags 0–{LAGS} of the monthly change in Kilian's index "
            f"(FRED `{DEMAND}`). The Hormuz case is an oil supply shock, with no demand boom behind it, so it "
            "probably sits nearer that column.", "",
            "## The 2026 closure: what the link expected and what happened", "",
            f"Fitted on months to {CLOSURE[0][:7]}, then given the Brent path that actually followed "
            f"(monthly average {np.exp(levels[BRENT][CLOSURE[0]]):.0f} → {np.exp(levels[BRENT][CLOSURE[1]]):.0f} "
            f"$/bbl, {100 * np.expm1(levels[BRENT][CLOSURE[1]] - levels[BRENT][CLOSURE[0]]):+.0f}%). Price change "
            f"{CLOSURE[0][:7]} → {CLOSURE[1][:7]}, %. \"Plus trend\" adds the fit's average monthly drift.", "",
            "| Series | What happened | Link: oil part | Link: oil part plus trend |", "|---|---|---|---|"]
    for code in [*SERIES, *CONTROLS]:
        c = res[code]["closure"]
        out.append(f"| {names[code]} | **{c['actual']:+.1f}** | {c['oil']:+.1f} | {c['trend']:+.1f} |")
    out += ["", "## Data", "",
            "| FRED | Series | Months used | Missing months since 2000 | Fetched | md5 |", "|---|---|---|---|---|---|"]
    for code, d in info.items():
        out.append(f"| `{code}` | {names[code]} | {max(d['first'], levels.index[0]):%Y-%m}..{d['last']:%Y-%m} | "
                   f"{d['missing']} | {d['fetched']} | `{d['md5']}` |")
    out += [
        "",
        "**Series choice.**",
        "",
        "- **Steel:** `WPU1017` (steel mill products) is complete from 2000. Scrap (`WPU1012`) is added "
        "because it was cheap; it is far more volatile (monthly sd about 8% against 3% for mill products).",
        "- **Aluminium:** on FRED (series pages checked 2026-10-24), `WPU102501` is **aluminum mill shapes**, "
        "complete from 2000. OXH-5 named `WPU102502` for mill shapes, but that code is **copper and brass "
        "mill shapes**, so it is not used. The primary-aluminium PPI (`PCU331313331313`, alumina refining and "
        "primary aluminum production) stops in 2019-03 and has 25 missing months (2010-01..2011-11, "
        "2016-12..2017-01), so it is not clean enough.",
        "- **World price check:** OXH-5 asked for LME aluminium. The closest free monthly series on FRED is "
        "the IMF's global aluminium benchmark (`PALUMUSDM`, $/t, period averages), used here in its place.",
        "",
        "**Caveats.**",
        "",
        "- These are average historical pass-throughs, mixing supply-driven and demand-driven oil moves "
        "(see the sensitivity table).",
        "- The PPIs are US prices of mill products (rolled and drawn steel and aluminium), not world crude "
        "steel or primary aluminium. US steel and aluminium prices also move with trade policy (Section 232 "
        "tariffs from 2018, raised again in 2025), which this link does not model.",
        "- In the 2026 closure, aluminium also took a direct hit: strikes on Gulf smelters on 28 Mar 2026 "
        "(`notes/materials/aluminium-fertiliser.md`). The closure table mixes that with the oil effect.",
        "",
    ]
    NOTE.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
