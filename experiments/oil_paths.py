# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scipy>=1.11", "xlrd>=2.0", "openpyxl>=3.1", "torch>=2.2",
#                 "jax>=0.4.30", "numpyro>=0.15"]
# ///
"""Monthly Brent paths from the GARCH-Lévy model of experiments/levy_fourier.py, for the knock-on
chain: the oil uncertainty of a genuine forecast, and the fan around a Hormuz scenario.

At each forecast origin (the end of month t):
- parameters: the GARCH(1,1) fit with CGMY innovations (Student-t with --innov t) in
  runs/levy/rolling-Y.json for the origin's year Y, fitted on daily returns before 1 January of Y,
  so nothing after the origin is used
- volatility: the GARCH filter over daily returns up to the origin's last trading day
- paths: daily returns over the business days of the next 12 months, by inverse-CDF sampling of
  the innovation, with the GARCH variance updated along each path (a big simulated move widens
  what follows). The paths are centred (mu removed) plus the futures-curve drift where it exists,
  as macro_bayes.oil_paths, so the two differ only in the volatility and tail model
- monthly changes: log of each month's mean price minus the previous month's, month 0 being the
  origin month's actual mean, because the knock-on panel's Brent is the monthly mean of daily spot
  (macro_data._monthly)
- scenario: an optional premium on the log price for `lost` points of Hormuz flow (held, or a
  monthly path such as the IEA's 2026 one, iea_lost_2026), from the curve in
  notes/flow-premium-iea.csv (experiments/flow_events.py iea: fitted to the 2026 closure per point
  of the IEA's lost strait flow, day by day, with a 90% band from 2019-2025 placebo days; checked
  out of sample against Bab el-Mandeb 2023-24; notes/hormuz-flow-check.md). The premium on a day is
  that day's loss times the curve. Each path draws its own place in the band. The premium also
  enters the GARCH update, so the band widens after the jump as it did in March 2026
- emergency stocks: `release` scales the premium by experiments/reserves.py's factor ("2026", the
  default, leaves it as fitted; "none" and "max" change how many of the lost barrels stocks replace)

    uv run experiments/oil_paths.py check   # backtest against the bootstrap paths -> notes/oil-paths-results.md
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from functools import lru_cache

import numpy as np
import pandas as pd

import levy_fourier as lf
import macro_bayes as mb
import macro_data as md
import macro_nn as mn
import reserves as rv

INNOV = {"cgmy": ("GARCH-CGMY", "levy"), "t": ("GARCH-Student-t", "student")}
N_PATHS = mb.DRAWS
LOST_2026 = 82.0  # PortWatch's trough loss in the 2026 closure (notes/flow-price-link.md); margins and reserves use it
# Log premium per point of the IEA's lost strait flow, by trading day. notes/flow-premium.csv is the
# older curve per point of PortWatch's trough (82); experiments/reserves.py still uses that pair.
PREMIUM = mb.NOTES / "flow-premium-iea.csv"
Z90 = 1.6449  # the CSV's band is a central 90% interval


def daily_brent() -> tuple[pd.Series, str]:
    """Daily Brent spot ($/bbl), the same cached FRED file the knock-on panel averages by month."""
    path = md._get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU", md.RAW / "fred_DCOILBRENTEU.csv")
    df = pd.read_csv(path, parse_dates=["observation_date"])
    s = pd.to_numeric(df["DCOILBRENTEU"], errors="coerce")
    s.index = df["observation_date"]
    return s.dropna(), datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat()


@lru_cache(maxsize=None)
def garch_levy(year: int, innov: str = "cgmy") -> tuple[float, float, float, float, object, str]:
    """(mu, omega, alpha, beta, innovation, source) fitted on daily returns before 1 January of year.
    Reads runs/levy/rolling-<year>.json; refits with levy_fourier.fit if it is missing."""
    name, kind = INNOV[innov]
    path = lf.RUNS / f"rolling-{year}.json"
    if path.exists():
        p = json.loads(path.read_text())["models"][name]["params"]
        if kind == "student":
            inn = lf.Student(p["nu"])
        else:
            Y = p["Y"] + (2e-9 if abs(p["Y"] - 1) < 1e-9 else 0.0)  # gamma(-Y) has a pole at 1, as in unpack
            inn = lf.Levy(p["G"], p["M"], Y, np.zeros(lf.K), np.zeros(lf.K))
        return p["mu"], p["omega"], p["alpha"], p["beta"], inn, f"runs/levy/{path.name}"
    prices, _ = lf.load_brent()
    r = np.log(prices).diff().dropna()
    spec = lf.Spec(name, kind)
    mu, omega, alpha, beta, inn = lf.unpack(spec, lf.fit(spec, r[r.index < f"{year}-01-01"].values))
    return mu, omega, alpha, beta, inn, f"refit on returns before {year}-01-01"


@lru_cache(maxsize=None)
def premium_curve() -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    """(e_low, e_mid, e_high, source) per trading day 1.. from PREMIUM. It is fitted to the 2026
    closure over the days observed and an assumption after that; the band is the 2019-2025 placebo
    range."""
    df = pd.read_csv(PREMIUM)
    assert (df["trading_day"].values == np.arange(1, len(df) + 1)).all(), f"{PREMIUM.name}: days not 1..n"
    return (df["e_low"].values, df["e_mid"].values, df["e_high"].values,
            f"notes/{PREMIUM.name} (generated {df['generated'].iloc[0]})")


@lru_cache(maxsize=None)
def iea_lost_2026() -> pd.Series:
    """Points of February 2026's strait flow lost in each month of the 2026 closure, from March, by
    the IEA's figures (notes/hormuz-iea-flows.csv via flow_events.iea_monthly): the loss the curve
    was fitted with (89 points in March to 47 in September; later months hold the last)."""
    import flow_events as fe

    strait = fe.iea_monthly(fe.iea_figures())["strait"].dropna()
    lost = 100 * (1 - strait / strait.iloc[0])
    return pd.Series(lost.to_numpy(float)[1:], index=lost.index[1:].to_timestamp())


def lost_on(lost, days: pd.DatetimeIndex) -> np.ndarray:
    """Points lost on each trading day: a number held throughout, or a monthly path (a Series by
    month start) giving each day its month's loss, the last month's held after it and 0 before it."""
    if np.ndim(lost) == 0:
        return np.full(len(days), float(lost))
    month = days.to_period("M").to_timestamp()
    return np.nan_to_num(lost.sort_index().reindex(month, method="ffill").to_numpy(float))


def premium(lost, days: int, z: np.ndarray, release: str = "2026") -> np.ndarray:
    """Log premium on Brent on trading days 1..days for `lost` points of Hormuz flow lost (one number
    for the whole path, or one per day), one row per path [len(z), days]: each day's loss times the
    curve. Path i sits at standard-normal score z[i] of the CSV's 90% band on every day (a split
    normal around e_mid, never below 0), so a path is a high- or a low-premium world throughout; days
    past the end of the CSV keep its last row. release: the emergency-stock policy (reserves.factor),
    for a held loss only; "2026" is the curve as fitted."""
    lo, mid, hi, _ = premium_curve()
    d = np.minimum(np.arange(days), len(mid) - 1)
    lo, mid, hi = lo[d], mid[d], hi[d]
    z = np.asarray(z, float)[:, None]
    e = np.where(z >= 0, mid + z * (hi - mid) / Z90, mid + z * (mid - lo) / Z90)
    if np.ndim(lost) == 0:
        f = 1.0 if release == "2026" or not lost else rv.factor(lost, release, days)
        return lost * np.maximum(e, 0.0) * f
    if release != "2026":
        raise ValueError("a release policy needs a held loss: experiments/reserves.py is restated on one")
    return np.asarray(lost, float)[None, :days] * np.maximum(e, 0.0)


def monthly_paths(prices: pd.Series, months: pd.DatetimeIndex, n: int, rng, innov: str = "cgmy",
                  drift: np.ndarray | None = None, lost=0.0, release: str = "2026") -> np.ndarray:
    """Monthly log changes of the mean Brent price in the 12 months after each origin month
    [n, len(months), 12], from daily GARCH-Lévy paths. drift: [len(months), 12] expected monthly
    log changes added to the paths (the futures curve); lost: points of Hormuz flow lost from the
    day after the origin, held, or a monthly path (lost_on; scenario); release: the emergency-stock
    policy (premium)."""
    logp = np.log(prices)
    r = logp.diff().dropna()
    out = np.zeros((n, len(months), mn.OIL_AHEAD))
    for i, m in enumerate(months):
        mu, omega, alpha, beta, inn, _ = garch_levy(m.year, innov)
        cdf_tab, x_tab = inn.table()
        end = m + pd.offsets.MonthEnd(0)
        past = r[r.index <= end].values
        s = lf.garch_sigma(past, mu, omega, alpha, beta)
        s2 = np.full(n, omega + alpha * (past[-1] - mu) ** 2 + beta * s[-1] ** 2)  # next trading day
        days = pd.bdate_range(end + pd.Timedelta(days=1), m + pd.DateOffset(months=mn.OIL_AHEAD + 1) - pd.Timedelta(days=1))
        month = (days.year - m.year) * 12 + days.month - m.month - 1  # 0..11
        count = np.bincount(month, minlength=mn.OIL_AHEAD)
        step = drift[i][month] / count[month] if drift is not None else np.zeros(len(days))
        loss = lost if np.ndim(lost) == 0 else lost_on(lost, days)
        z = rng.standard_normal(n) if np.any(loss) else np.zeros(n)  # drawn only with a scenario: lost=0 paths are unchanged
        prem = premium(loss, len(days), z, release)  # [n, days]
        jump = np.diff(np.column_stack([np.zeros(n), prem]), axis=1)
        x, total = np.zeros(n), np.zeros((n, mn.OIL_AHEAD))  # x: log price relative to the last close
        u = rng.random((len(days), n))
        for d in range(len(days)):
            e = np.sqrt(s2) * np.interp(u[d], cdf_tab, x_tab)
            x = x + e + step[d]
            s2 = omega + alpha * (e + jump[:, d]) ** 2 + beta * s2  # the scenario's jump is part of the return
            total[:, month[d]] += np.exp(x + prem[:, d])
        level = np.log(total / count) + logp[logp.index <= end].iloc[-1]
        base = np.log(prices[(prices.index >= m) & (prices.index <= end)].mean())  # month 0: actual mean
        out[:, i] = np.diff(np.column_stack([np.full(n, base), level]), axis=1)
    return out


# --- backtest --------------------------------------------------------------------------------

def check() -> None:
    """Brent's change over 1, 3, 6 and 12 months after each of the 214 test origins: CRPS and 90%
    coverage of the GARCH-Lévy paths against macro_bayes.oil_paths (block bootstrap of training
    months, OVX-scaled, futures-centred), on the same folds."""
    data = mn.make_dataset(mn.V1_BLOCKS)
    prices, fetched = daily_brent()
    idx = mb.month_index(data)
    # the daily file and the panel must agree: monthly means of the daily prices give the panel's changes
    monthly = np.log(prices.resample("MS").mean()).diff().reindex(idx).values
    ok = np.isfinite(monthly) & np.isfinite(data["oil_m"])
    gap = float(np.max(np.abs(monthly[ok] - data["oil_m"][ok])))
    assert gap < 1e-9, f"daily Brent file and panel disagree by {gap}"
    market = mb.market_inputs(data)
    H = np.array(mn.HORIZONS)
    models = ("GARCH-CGMY", "GARCH-Student-t", "bootstrap")
    crps = {m: [] for m in models}
    inside = {m: [] for m in models}
    pit = {m: [] for m in models}
    dates, y_all = [], []
    for j in range(mn.FOLDS):
        _, test, last = mb.fold_window(data, j)
        st = mb.Stats(data, last)
        t = data["t"][test]
        y = np.cumsum(data["OIL"][test], 1)[:, H - 1] * 100  # realised % log change over each horizon
        paths = {"GARCH-CGMY": monthly_paths(prices, idx[t], N_PATHS, np.random.default_rng(700 + j), "cgmy", market["drift"][t]),
                 "GARCH-Student-t": monthly_paths(prices, idx[t], N_PATHS, np.random.default_rng(700 + j), "t", market["drift"][t]),
                 "bootstrap": mb.oil_paths(data, st, last, t, N_PATHS, np.random.default_rng(700 + j), market)}
        for m, P in paths.items():
            S = np.cumsum(P, -1)[..., H - 1] * 100  # [N, O, horizons]
            crps[m].append(mb.crps_samples(S, y))
            lo, hi = np.quantile(S, 0.05, 0), np.quantile(S, 0.95, 0)
            inside[m].append((y >= lo) & (y <= hi))
            pit[m].append((S <= y[None]).mean(0))
        dates += [f"{d:%Y-%m}" for d in data["dates"][test]]
        y_all.append(y)
        print(f"fold {j}: " + ", ".join(f"{m} {np.mean(crps[m][-1]):.2f}" for m in models), flush=True)
    C = {m: np.vstack(v) for m, v in crps.items()}
    IN = {m: np.vstack(v) for m, v in inside.items()}
    PIT = {m: np.vstack(v) for m, v in pit.items()}
    crisis_months = pd.DatetimeIndex([])
    for lo, hi in mn.CRISES:
        crisis_months = crisis_months.union(pd.date_range(lo, hi, freq="MS"))
    origin = pd.to_datetime(dates)
    crisis = np.array([any(o + pd.DateOffset(months=k) in crisis_months for k in range(1, 13)) for o in origin])
    sources = sorted({garch_levy(int(d[:4]), "cgmy")[5] for d in dates})
    RUNS = mb.RUNS
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / "oil-paths-check.json").write_text(json.dumps(
        {"dates": dates, "horizons": H.tolist(), "y": np.vstack(y_all).tolist(),
         "models": {m: {"crps": C[m].tolist(), "pit": PIT[m].tolist()} for m in models}}))

    out = ["# Lévy oil paths: backtest of the oil layer", "",
           f"_Generated by `experiments/oil_paths.py check` on {datetime.now(UTC).date().isoformat()}. Daily Brent: "
           f"FRED DCOILBRENTEU (EIA), `data/raw/macro/fred_DCOILBRENTEU.csv` fetched {fetched}; its monthly means "
           f"reproduce the knock-on panel's Brent changes (largest difference {gap:.1e}). {len(dates)} forecast origins "
           f"({dates[0]}..{dates[-1]}) on the 8 folds of `notes/macro-bayes-results.md`. GARCH-Lévy parameters: "
           f"{sources[0]} .. {sources[-1]}, each fitted on daily returns before 1 January of the origin's year. "
           "Futures drift: EIA WTI RCLC1-4 (to 2024-04) for every model. The paths are simulated; the outcomes are "
           f"real. {N_PATHS} paths per origin._", "",
           "Target: Brent's log change (%, ×100) of the monthly mean price from the origin month to h months "
           "later, the input the knock-on models take. CRPS is in percentage points (lower is better). "
           "`bootstrap` is the forecast mode of `macro_bayes.py`: 3-month blocks of training months, scaled to "
           "the OVX implied volatility at the origin.", "",
           "## Accuracy and calibration", "",
           "| h (months) | " + " | ".join(f"{m} CRPS" for m in models) + " | CGMY − bootstrap (t) | "
           + " | ".join(f"{m} in 90%" for m in models) + " |",
           "|---|" + "---|" * (2 * len(models) + 1)]
    for hi, h in enumerate(H):
        d = C["GARCH-CGMY"][:, hi] - C["bootstrap"][:, hi]
        out.append(f"| {h} | " + " | ".join(f"{C[m][:, hi].mean():.2f}" for m in models)
                   + f" | {d.mean():+.2f} (t {mb.nw_t(d, lags=max(h, 1)):+.1f}) | "
                   + " | ".join(f"{IN[m][:, hi].mean():.0%}" for m in models) + " |")
    out += ["", "## Crisis and calm origins", "",
            f"Origins whose next 12 months touch a crisis window ({', '.join(f'{lo[:7]} to {hi[:7]}' for lo, hi in mn.CRISES)}): "
            f"{crisis.sum()} of {len(origin)}.", "",
            "| h | Origins | " + " | ".join(f"{m} CRPS" for m in models) + " | " + " | ".join(f"{m} in 90%" for m in models) + " |",
            "|---|---|" + "---|" * (2 * len(models))]
    for label, sel in (("calm", ~crisis), ("crisis", crisis)):
        for hi, h in enumerate(H):
            out.append(f"| {h}, {label} | {sel.sum()} | " + " | ".join(f"{C[m][sel, hi].mean():.2f}" for m in models)
                       + " | " + " | ".join(f"{IN[m][sel, hi].mean():.0%}" for m in models) + " |")
    out += ["", "## Tails: share of outcomes below the 5% and above the 95% quantile (target 5% each)", "",
            "| h | " + " | ".join(f"{m} low / high" for m in models) + " |", "|---|" + "---|" * len(models)]
    for hi, h in enumerate(H):
        out.append(f"| {h} | " + " | ".join(f"{(PIT[m][:, hi] < 0.05).mean():.0%} / {(PIT[m][:, hi] > 0.95).mean():.0%}"
                                            for m in models) + " |")
    (mb.NOTES / "oil-paths-results.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {mb.NOTES / 'oil-paths-results.md'}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("check",))
    p.parse_args()
    check()


if __name__ == "__main__":
    main()
