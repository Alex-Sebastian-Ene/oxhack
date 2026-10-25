# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1"]
# ///
"""Validate the links of the knock-on chain in docs/design.md (section 4) on US history from FRED.

    oil price -> petrol -> energy CPI -> headline CPI -> core CPI -> inflation expectations
              -> Fed funds rate -> mortgage rate

Each link is a small regression on monthly averages with Newey-West standard errors. Links are
fitted on TRAIN and then used, unchanged, to predict TEST (out-of-sample R^2 against the training
mean), so a link only counts if it carries over to years it never saw. The last table chains the
fitted links for a 10% oil-price rise, which is what the "what if" slider needs.

    uv run experiments/oil_chain.py      # fetches the series into data/raw/, writes notes/oil-chain-links.md
    uv run experiments/oil_chain.py cv   # blocked and forward k-fold, k = 8..16: notes/oil-chain-cv.md
"""

from __future__ import annotations

import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "notes" / "oil-chain-links.md"
CV_OUT = ROOT / "notes" / "oil-chain-cv.md"
FOLDS = range(8, 17)  # k for the fold-level split tests
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
TRAIN, TEST = ("1991-01-01", "2008-12-31"), ("2009-01-01", "2026-12-31")
SHOCK = 0.10  # oil-price rise used for the chained example

SERIES = {
    "DCOILBRENTEU": "Brent spot, $/bbl (daily; EIA)",
    "GASREGW": "US regular petrol retail, $/gal (weekly; EIA)",
    "CPIENGSL": "CPI energy (monthly, SA; BLS)",
    "CPIAUCSL": "CPI all items (monthly, SA; BLS)",
    "CPILFESL": "CPI less food and energy (monthly, SA; BLS)",
    "T5YIE": "5-year breakeven inflation, % (daily; Federal Reserve Bank of St. Louis)",
    "FEDFUNDS": "Effective federal funds rate, % (monthly; Federal Reserve)",
    "UNRATE": "Unemployment rate, % (monthly, SA; BLS)",
    "MORTGAGE30US": "30-year fixed mortgage rate, % (weekly; Freddie Mac)",
    "DGS10": "10-year Treasury yield, % (daily; Federal Reserve)",
}


def fetch(series: str) -> tuple[pd.Series, str]:
    """Monthly average of a FRED series, cached under data/raw/ (git-ignored)."""
    path = RAW / f"{series}.csv"
    if not path.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(FRED_URL.format(series), path)
    fetched = datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat()
    df = pd.read_csv(path, parse_dates=["observation_date"])
    s = pd.to_numeric(df[series], errors="coerce")
    s.index = df["observation_date"]
    return s.dropna().resample("MS").mean(), fetched


def ols_hac(y: np.ndarray, X: np.ndarray, lag: int):
    """OLS coefficients with a Newey-West covariance."""
    inv = np.linalg.inv(X.T @ X)
    b = inv @ X.T @ y
    u = X * (y - X @ b)[:, None]
    S = u.T @ u
    for k in range(1, lag + 1):
        G = u[k:].T @ u[:-k]
        S += (1 - k / (lag + 1)) * (G + G.T)
    return b, inv @ S @ inv


def design(y: pd.Series, regressors: dict[str, pd.Series], lags: int) -> pd.DataFrame:
    cols = {"y": y, "const": pd.Series(1.0, index=y.index)}
    for name, x in regressors.items():
        for j in range(lags + 1):
            cols[f"{name}_{j}"] = x.shift(j)
    return pd.DataFrame(cols).dropna()


def link(name, y, regressors, lags, hac_lag, scale, unit, train=TRAIN, test=TEST, cumulate="oil"):
    """Fit y on lags 0..lags of each regressor; report the summed effect of `cumulate`."""
    d = design(y, regressors, lags)
    tr, te = d.loc[train[0]:train[1]], d.loc[test[0]:test[1]]
    X_cols = [c for c in d.columns if c != "y"]
    b, cov = ols_hac(tr["y"].values, tr[X_cols].values, hac_lag)
    idx = [i for i, c in enumerate(X_cols) if c.startswith(cumulate + "_")]
    total = b[idx].sum() * scale
    se = np.sqrt(np.ones(len(idx)) @ cov[np.ix_(idx, idx)] @ np.ones(len(idx))) * scale
    resid_tr = tr["y"].values - tr[X_cols].values @ b
    r2 = 1 - resid_tr.var() / tr["y"].var()
    pred = te[X_cols].values @ b
    r2_oos = 1 - np.sum((te["y"].values - pred) ** 2) / np.sum((te["y"].values - tr["y"].mean()) ** 2)
    b_te, cov_te = ols_hac(te["y"].values, te[X_cols].values, hac_lag)
    total_te = b_te[idx].sum() * scale
    se_te = np.sqrt(np.ones(len(idx)) @ cov_te[np.ix_(idx, idx)] @ np.ones(len(idx))) * scale
    return {"name": name, "total": total, "se": se, "unit": unit, "r2": r2, "r2_oos": r2_oos,
            "total_test": total_te, "se_test": se_te, "n_train": len(tr), "n_test": len(te),
            "lags": lags, "train": f"{tr.index[0]:%Y-%m}..{tr.index[-1]:%Y-%m}",
            "test": f"{te.index[0]:%Y-%m}..{te.index[-1]:%Y-%m}"}


def taylor(core_yoy: pd.Series, unrate: pd.Series, ff: pd.Series, era: tuple[str, str]) -> dict:
    """Fed funds level on last month's core inflation and unemployment, outside the zero lower bound."""
    d = pd.DataFrame({"y": ff, "const": 1.0, "pi": core_yoy.shift(1), "u": unrate.shift(1)}).dropna()
    d = d.loc[era[0]:era[1]]
    d = d[d["y"] > 0.5]
    b, cov = ols_hac(d["y"].values, d[["const", "pi", "u"]].values, 12)
    return {"era": f"{d.index[0]:%Y-%m}..{d.index[-1]:%Y-%m}", "n": len(d), "b_pi": b[1],
            "se_pi": np.sqrt(cov[1, 1]), "b_u": b[2], "se_u": np.sqrt(cov[2, 2])}


def blocked_folds(n: int, k: int, purge: int):
    """k contiguous test blocks over n rows; training is every other row except `purge` either side."""
    edges = np.linspace(0, n, k + 1).round().astype(int)
    for lo, hi in zip(edges[:-1], edges[1:]):
        test = np.zeros(n, bool)
        test[lo:hi] = True
        train = np.ones(n, bool)
        train[max(0, lo - purge):hi + purge] = False
        yield train, test


def cv_link(spec: dict, k: int, forward: bool = False) -> dict:
    """Cross-validate one link over its whole window with k blocks.

    Blocked: each block is held out once and the link is fitted on all other blocks, minus a gap of
    `lags` months either side so lagged regressors cannot straddle the cut. Forward: each block is
    predicted from the blocks before it only (skipping blocks with under 3 years of past data).
    """
    window = (spec.get("train", TRAIN)[0], spec.get("test", TEST)[1])
    d = design(spec["y"], spec["regressors"], spec["lags"]).loc[window[0]:window[1]]
    cols = [c for c in d.columns if c != "y"]
    idx = [i for i, c in enumerate(cols) if c.startswith(spec.get("cumulate", "oil") + "_")]
    X, y = d[cols].values, d["y"].values
    purge = max(spec["lags"], 1)
    effects, r2, sse, sst = [], [], 0.0, 0.0
    for train, test in blocked_folds(len(y), k, purge):
        if forward:
            train = np.arange(len(y)) < np.argmax(test) - purge
            if train.sum() < 36:
                continue
        b = np.linalg.lstsq(X[train], y[train], rcond=None)[0]
        e = np.sum((y[test] - X[test] @ b) ** 2)
        s = np.sum((y[test] - y[train].mean()) ** 2)
        effects.append(b[idx].sum() * spec["scale"])
        r2.append(1 - e / s)
        sse, sst = sse + e, sst + s
    return {"k": k, "effects": np.array(effects), "r2": np.array(r2), "pooled_r2": 1 - sse / sst,
            "window": f"{d.index[0]:%Y-%m}..{d.index[-1]:%Y-%m}", "months": len(y)}


def full_window_effect(spec: dict) -> tuple[float, float]:
    """The link fitted on its whole window, with a Newey-West standard error."""
    window = (spec.get("train", TRAIN)[0], spec.get("test", TEST)[1])
    d = design(spec["y"], spec["regressors"], spec["lags"]).loc[window[0]:window[1]]
    cols = [c for c in d.columns if c != "y"]
    idx = [i for i, c in enumerate(cols) if c.startswith(spec.get("cumulate", "oil") + "_")]
    b, cov = ols_hac(d["y"].values, d[cols].values, spec["hac_lag"])
    ones = np.ones(len(idx))
    return b[idx].sum() * spec["scale"], float(np.sqrt(ones @ cov[np.ix_(idx, idx)] @ ones)) * spec["scale"]


def cv_taylor(core_yoy: pd.Series, unrate: pd.Series, ff: pd.Series, k: int) -> np.ndarray:
    """The Taylor-rule inflation coefficient from each blocked fold (months above the lower bound)."""
    d = pd.DataFrame({"y": ff, "const": 1.0, "pi": core_yoy.shift(1), "u": unrate.shift(1)}).dropna()
    d = d.loc["1991-01-01":]
    d = d[d["y"] > 0.5]
    X, y = d[["const", "pi", "u"]].values, d["y"].values
    return np.array([np.linalg.lstsq(X[tr], y[tr], rcond=None)[0][1] for tr, _ in blocked_folds(len(y), k, 12)])


def load_inputs():
    data, fetched = {}, {}
    for sid in SERIES:
        data[sid], fetched[sid] = fetch(sid)
    dl = {k: np.log(v).diff() for k, v in data.items() if k in ("DCOILBRENTEU", "GASREGW", "CPIENGSL",
                                                                   "CPIAUCSL", "CPILFESL")}
    return data, fetched, dl


def link_specs(data: dict, dl: dict) -> list[dict]:
    """The household chain: one dict of `link()` arguments per link."""
    oil, pct = dl["DCOILBRENTEU"], SHOCK * 100
    rates = {"ten": data["DGS10"].diff(), "ff": data["FEDFUNDS"].diff()}
    month2, year = "% for a 10% oil rise, within 2 months", "% (pp of price level) within 12 months"
    return [
        dict(name="Oil -> petrol price", y=dl["GASREGW"], regressors={"oil": oil}, lags=2, hac_lag=6,
             scale=pct, unit=month2),
        dict(name="Oil -> energy CPI", y=dl["CPIENGSL"], regressors={"oil": oil}, lags=2, hac_lag=6,
             scale=pct, unit=month2),
        dict(name="Oil -> headline CPI", y=dl["CPIAUCSL"], regressors={"oil": oil}, lags=12, hac_lag=12,
             scale=pct, unit=year),
        dict(name="Oil -> core CPI", y=dl["CPILFESL"], regressors={"oil": oil}, lags=12, hac_lag=12,
             scale=pct, unit=year),
        dict(name="Oil -> 5y inflation expectations", y=data["T5YIE"].diff(), regressors={"oil": oil},
             lags=1, hac_lag=6, scale=SHOCK, unit="pp for a 10% oil rise",
             train=("2003-01-01", "2013-12-31"), test=("2014-01-01", "2026-12-31")),
        dict(name="10y Treasury -> mortgage rate", y=data["MORTGAGE30US"].diff(), regressors=rates, lags=1,
             hac_lag=6, scale=1.0, unit="pp per 1 pp move in the 10y yield, within a month", cumulate="ten"),
        dict(name="Fed funds -> mortgage rate (holding 10y)", y=data["MORTGAGE30US"].diff(), regressors=rates,
             lags=1, hac_lag=6, scale=1.0, unit="pp per 1 pp move in fed funds, within a month", cumulate="ff"),
    ]


def main() -> None:
    data, fetched, dl = load_inputs()
    core_yoy = 100 * np.log(data["CPILFESL"]).diff(12)
    links = [link(**spec) for spec in link_specs(data, dl)]
    rules = [taylor(core_yoy, data["UNRATE"], data["FEDFUNDS"], era) for era in
             (("1991-01-01", "2008-12-31"), ("2016-01-01", "2026-12-31"))]

    by = {l["name"]: l for l in links}
    headline, core = by["Oil -> headline CPI"], by["Oil -> core CPI"]
    fed = rules[0]["b_pi"] * core["total"]
    fed_se = np.hypot(rules[0]["b_pi"] * core["se"], rules[0]["se_pi"] * core["total"])
    write_report(links, rules, fetched, data, headline, core, fed, fed_se, by)


def write_report(links, rules, fetched, data, headline, core, fed, fed_se, by) -> None:
    out = [
        "# Knock-on chain: does each link hold up in the data?",
        "",
        f"_Generated by `experiments/oil_chain.py` on {datetime.now(UTC).date().isoformat()}. All series from "
        "FRED (St. Louis Fed), monthly averages, US. Fetched: "
        + "; ".join(f"{k} {fetched[k]} ({data[k].index[0]:%Y-%m}..{data[k].index[-1]:%Y-%m})" for k in SERIES)
        + ". Nothing here is synthetic._",
        "",
        "Each link regresses the monthly change of the downstream series on the current and lagged "
        "monthly change of the upstream one (log changes for prices, level changes for rates). The "
        "effect is the sum of the lag coefficients, with a Newey-West ± (1 standard error). Fitted on "
        "the train years, then used unchanged on the test years: **out-of-sample R² > 0** means the "
        "link predicts better than a constant there. \"Test-years refit\" re-estimates on the test "
        "years alone, to show whether the size of the link has drifted.",
        "",
        "| Link | Effect (train) | Unit | In-sample R² | Out-of-sample R² | Test-years refit | Train / test |",
        "|---|---|---|---|---|---|---|",
    ]
    for l in links:
        out.append(f"| {l['name']} | **{l['total']:+.3f} ± {l['se']:.3f}** | {l['unit']} | {l['r2']:.2f} | "
                   f"{l['r2_oos']:+.2f} | {l['total_test']:+.3f} ± {l['se_test']:.3f} | {l['train']} / {l['test']} |")
    out += [
        "",
        "## Fed reaction (Taylor-style rule, months with fed funds above 0.5%)",
        "",
        "Fed funds level on last month's 12-month core CPI inflation and unemployment. Levels are "
        "highly persistent, so read these as descriptive; the coefficient on inflation is the Fed's "
        "rate response per 1 pp of core inflation.",
        "",
        "| Era | Months | Inflation coefficient | Unemployment coefficient |",
        "|---|---|---|---|",
    ] + [f"| {r['era']} | {r['n']} | {r['b_pi']:+.2f} ± {r['se_pi']:.2f} | {r['b_u']:+.2f} ± {r['se_u']:.2f} |"
         for r in rules] + [
        "",
        "## The chain for a 10% oil-price rise (train-period links)",
        "",
        "| Step | Modelled change |",
        "|---|---|",
        f"| Petrol price | {by['Oil -> petrol price']['total']:+.2f}% ± {by['Oil -> petrol price']['se']:.2f} |",
        f"| Energy CPI | {by['Oil -> energy CPI']['total']:+.2f}% ± {by['Oil -> energy CPI']['se']:.2f} |",
        f"| Headline CPI level after 12 months | {headline['total']:+.2f} pp ± {headline['se']:.2f} |",
        f"| Core CPI level after 12 months | {core['total']:+.2f} pp ± {core['se']:.2f} |",
        f"| 5y inflation expectations | {by['Oil -> 5y inflation expectations']['total']:+.3f} pp "
        f"± {by['Oil -> 5y inflation expectations']['se']:.3f} |",
        f"| Fed funds (Taylor response to the core effect) | {100 * fed:+.0f} bp ± {100 * fed_se:.0f} |",
        f"| 30y mortgage via fed funds (holding the 10y) | "
        f"{100 * fed * by['Fed funds -> mortgage rate (holding 10y)']['total']:+.1f} bp |",
        "",
        "Read with care: these are average historical pass-throughs, not causal effects of a supply "
        "shock specifically, and the Fed step multiplies two estimates (its ± combines both errors, "
        "ignoring their correlation).",
        "",
    ]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


def verdict(blocked: dict, effects: np.ndarray, r2: np.ndarray, sign: float) -> str:
    pooled = np.array([res["pooled_r2"] for res in blocked.values()])
    same = np.mean(np.sign(effects) == np.sign(sign))
    if pooled.min() > 0 and np.mean(r2 > 0) >= 0.8 and same >= 0.9:
        return "**Holds** at every k"
    if pooled.min() > 0:
        return "Predicts on average, but not in every fold"
    if pooled.max() > 0:
        return "Depends on k"
    return "**Fails**: never beats a constant"


def run_cv() -> None:
    data, fetched, dl = load_inputs()
    core_yoy = 100 * np.log(data["CPILFESL"]).diff(12)
    summary, per_k = [], []
    for spec in link_specs(data, dl):
        blocked = {k: cv_link(spec, k) for k in FOLDS}
        forward = {k: cv_link(spec, k, forward=True) for k in FOLDS}
        effects = np.concatenate([res["effects"] for res in blocked.values()])
        r2 = np.concatenate([res["r2"] for res in blocked.values()])
        full, full_se = full_window_effect(spec)
        pb = [res["pooled_r2"] for res in blocked.values()]
        pf = [res["pooled_r2"] for res in forward.values()]
        lo, med, hi = np.quantile(effects, [0.05, 0.5, 0.95])
        summary.append(
            f"| {spec['name']} | {blocked[8]['window']} | {full:+.3f} ± {full_se:.3f} | "
            f"{min(pb):+.2f} to {max(pb):+.2f} | {min(pf):+.2f} to {max(pf):+.2f} | "
            f"{np.mean(r2 > 0):.0%} of {len(r2)} | {med:+.3f} [{lo:+.3f}, {hi:+.3f}] | "
            f"{np.mean(np.sign(effects) == np.sign(full)):.0%} | {verdict(blocked, effects, r2, full)} |")
        per_k.append(f"| {spec['name']} | " + " | ".join(f"{p:+.2f}" for p in pb) + " |")
        print(f"{spec['name']}: blocked pooled R2 {min(pb):+.2f}..{max(pb):+.2f}", flush=True)
    taylor_rows = []
    for k in FOLDS:
        b = cv_taylor(core_yoy, data["UNRATE"], data["FEDFUNDS"], k)
        taylor_rows.append(f"| {k} | {np.median(b):+.2f} | {b.min():+.2f} to {b.max():+.2f} |")

    ks = list(FOLDS)
    out = [
        "# Knock-on chain: fold-level split testing (k = 8 to 16)",
        "",
        f"_Generated by `experiments/oil_chain.py cv` on {datetime.now(UTC).date().isoformat()}. Same FRED "
        "series and link definitions as `notes/oil-chain-links.md` (fetched "
        + ", ".join(sorted(set(fetched.values()))) + "). Nothing here is synthetic._",
        "",
        "The single split in `notes/oil-chain-links.md` (train 1991–2008, test 2009–2026) depends on "
        "where the cut falls. Here each link's whole window is cut into k contiguous blocks, for every "
        f"k from {ks[0]} to {ks[-1]}, which gives {sum(ks)} folds per link.",
        "",
        "- **Blocked:** each block is held out once, and the link is fitted on all the other blocks. "
        "A gap the length of the link's lags is left either side of the block, so lagged regressors "
        "cannot straddle the cut.",
        "- **Forward:** each block is predicted only from the blocks before it. Blocks with under 3 "
        "years of past data are skipped. This is the time-honest version.",
        "- **R²** is out of sample, against the training mean. **Pooled R²** combines all the folds "
        "for one k. **Fold effects** are the link's summed lag coefficient in each fold, in the units "
        "of `notes/oil-chain-links.md`.",
        "",
        "| Link | Window | Effect, whole window | Blocked pooled R², over k | Forward pooled R², over k | Folds with R² > 0 | Fold effects: median [5%, 95%] | Same sign as whole window | Verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ] + summary + [
        "",
        "The two mortgage rows are one regression on the 10-year yield and fed funds together, so they "
        "share its R². Judge the fed-funds row by its effect, whose fold range straddles zero.",
        "",
        "Blocked pooled out-of-sample R² for each k:",
        "",
        "| Link | " + " | ".join(f"k={k}" for k in ks) + " |",
        "|---|" + "---|" * len(ks),
    ] + per_k + [
        "",
        "## Fed reaction across folds",
        "",
        "Taylor-rule coefficient on last month's core inflation, refitted with each blocked fold held "
        "out (months with fed funds above 0.5%, 1991 onwards, 12-month gap either side).",
        "",
        "| k | Median coefficient | Range across folds |",
        "|---|---|---|",
    ] + taylor_rows + [""]
    CV_OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {CV_OUT}")


if __name__ == "__main__":
    import sys

    run_cv() if sys.argv[1:] == ["cv"] else main()
