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

    uv run experiments/oil_chain.py   # fetches the series into data/raw/, writes notes/oil-chain-links.md
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


def main() -> None:
    data, fetched = {}, {}
    for sid in SERIES:
        data[sid], fetched[sid] = fetch(sid)
    dl = {k: np.log(v).diff() for k, v in data.items() if k in ("DCOILBRENTEU", "GASREGW", "CPIENGSL",
                                                                   "CPIAUCSL", "CPILFESL")}
    oil = dl["DCOILBRENTEU"]
    core_yoy = 100 * np.log(data["CPILFESL"]).diff(12)
    pct = SHOCK * 100

    links = [
        link("Oil -> petrol price", dl["GASREGW"], {"oil": oil}, 2, 6, pct, "% for a 10% oil rise, within 2 months"),
        link("Oil -> energy CPI", dl["CPIENGSL"], {"oil": oil}, 2, 6, pct, "% for a 10% oil rise, within 2 months"),
        link("Oil -> headline CPI", dl["CPIAUCSL"], {"oil": oil}, 12, 12, pct, "% (pp of price level) within 12 months"),
        link("Oil -> core CPI", dl["CPILFESL"], {"oil": oil}, 12, 12, pct, "% (pp of price level) within 12 months"),
        link("Oil -> 5y inflation expectations", data["T5YIE"].diff(), {"oil": oil}, 1, 6, SHOCK,
             "pp for a 10% oil rise", train=("2003-01-01", "2013-12-31"), test=("2014-01-01", "2026-12-31")),
        link("10y Treasury -> mortgage rate", data["MORTGAGE30US"].diff(),
             {"ten": data["DGS10"].diff(), "ff": data["FEDFUNDS"].diff()}, 1, 6, 1.0,
             "pp per 1 pp move in the 10y yield, within a month", cumulate="ten"),
        link("Fed funds -> mortgage rate (holding 10y)", data["MORTGAGE30US"].diff(),
             {"ten": data["DGS10"].diff(), "ff": data["FEDFUNDS"].diff()}, 1, 6, 1.0,
             "pp per 1 pp move in fed funds, within a month", cumulate="ff"),
    ]
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


if __name__ == "__main__":
    main()
