# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1"]
# ///
"""Emergency oil stocks as a buffer between lost Hormuz flow and Brent, and stock cover by country.

The flow-premium curve (notes/flow-premium.csv, experiments/flow_events.py) is Brent's log premium per
point of *gross* lost Hormuz flow in the 2026 closure. During that closure governments released emergency
stocks (notes/reserves/releases-2026.csv), so part of the lost barrels never went missing from the market.
Here the curve is restated per point of *net* loss, which lets a scenario change the release:

- release_2026(c): barrels a day released on calendar day c of the 2026 closure (day 0 = its start,
  2026-03-04), each tranche's volume spread evenly over its delivery window
- net26(c) = LOST_2026 - 100 * release_2026(c) / PREWAR, in points of normal Hormuz flow
- a scenario with `lost` gross points and release r(c) has net(c) = lost - 100 * r(c) / PREWAR and log
  premium e(d) * LOST_2026 * net(c) / net26(c) on trading day d (calendar day c), i.e. the curve times
  factor(d) = LOST_2026 * net(c) / (lost * net26(c))
- policies: "2026" replaces the same share of the lost barrels as 2026 did on each day (factor 1: the
  chain as it is); "none" releases nothing; "max" releases at the IEA's maximum drawdown rate, as much as
  25 mb/d for two months and then falling (here: in a straight line to nothing at six months; CRS R45281
  citing the IEA). No policy releases more than the barrels lost, and every one stops when the stocks held
  for release (notes/reserves/stocks.csv, rows marked releasable) run out; those barrels then go missing
- the assumption: Brent's premium is proportional to the net barrels missing. One event cannot test it,
  and the bypass pipelines stay inside the curve as they were in 2026

Country cover (notes/reserves/country-cover.csv): each country's stocks in its source's unit (IEA days of net
imports, our JODI days of demand, an EIA volume estimate or an official claim), and how long they would replace
its lost Hormuz oil at a given lost flow (the app's country table gives the oil it received through Hormuz
before the war). The report also shows the chain's 2026 replay under each policy when those tables exist.

    uv run experiments/reserves.py   # writes notes/reserves.md and notes/reserve-scenarios.csv
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "notes"
DATA = NOTES / "reserves"
RELEASES = DATA / "releases-2026.csv"
STOCKS = DATA / "stocks.csv"
COVER = DATA / "country-cover.csv"
PREMIUM = NOTES / "flow-premium.csv"
OUT = NOTES / "reserves.md"
TABLE = NOTES / "reserve-scenarios.csv"

START = pd.Timestamp("2026-03-04")  # the 2026 closure's day 0 (flow_events.closure_start)
LOST_2026 = 82.0  # points of Hormuz flow lost in the 2026 closure (oil_paths.LOST_2026)
PREWAR = 20.0  # million barrels a day through Hormuz before the war (EIA; the app's PREWAR)
YEAR = 252  # trading days the app averages Brent over (patch_chain.PREM)
POLICIES = ("2026", "none", "max")
MAX_FULL, MAX_END = 61, 182  # calendar days: the maximum rate holds for two months, then falls to nothing by six


# --- data ------------------------------------------------------------------------------------

def releases() -> pd.DataFrame:
    """The 2026 release tranches: holder, start, end (delivery window, inclusive), volume_mb, source."""
    df = pd.read_csv(RELEASES, parse_dates=["start", "end"])
    assert (df["end"] >= df["start"]).all() and (df["volume_mb"] > 0).all(), "releases-2026.csv: bad window or volume"
    return df


def stocks() -> pd.DataFrame:
    df = pd.read_csv(STOCKS)
    assert set(df["releasable"]) <= {"yes", "no"}, "stocks.csv: releasable is yes or no"
    return df


def buffer() -> tuple[float, float]:
    """(stock held for release, million barrels; combined maximum release rate, mb/d) from stocks.csv."""
    s = stocks()
    r = s[s["releasable"] == "yes"]
    return float(r["volume_mb"].sum()), float(r["max_rate_mbd"].fillna(0).sum())


def curve(days: int | None = None) -> pd.DataFrame:
    df = pd.read_csv(PREMIUM)
    assert (df["trading_day"].values == np.arange(1, len(df) + 1)).all(), "flow-premium.csv: days not 1..n"
    return df if days is None else df.iloc[np.minimum(np.arange(days), len(df) - 1)].reset_index(drop=True)


# --- the buffer ------------------------------------------------------------------------------

def calendar_days(days: int, start: pd.Timestamp = START) -> np.ndarray:
    """Calendar day (0 = start) of trading days 1..days, weekdays only (as oil_paths' daily paths)."""
    b = pd.bdate_range(start, periods=days + 1)
    return np.asarray((b[1:] - b[0]).days)


def release_2026(n: int, tranches: pd.DataFrame | None = None, start: pd.Timestamp = START) -> np.ndarray:
    """Million barrels a day released on calendar days 0..n-1 of the 2026 closure."""
    tranches = releases() if tranches is None else tranches
    r = np.zeros(n)
    for t in tranches.itertuples():
        a, b = (t.start - start).days, (t.end - start).days
        r[max(a, 0):max(min(b + 1, n), 0)] += t.volume_mb / (b - a + 1)
    return r


def release_path(lost: float, policy: str, n: int, stock: float, rate: float, r26: np.ndarray) -> np.ndarray:
    """Million barrels a day released on calendar days 0..n-1 for `lost` gross points under a policy,
    never more than the barrels lost, stopping when `stock` million barrels have gone."""
    gap = lost / 100 * PREWAR
    if policy == "2026":
        want = r26[:n] / (LOST_2026 / 100 * PREWAR) * gap  # the same share of the lost barrels as in 2026
    elif policy == "none":
        want = np.zeros(n)
    elif policy == "max":
        want = rate * np.clip((MAX_END - np.arange(n)) / (MAX_END - MAX_FULL), 0.0, 1.0)
    else:
        raise ValueError(policy)
    want = np.minimum(want, gap)
    left = np.maximum(stock - np.concatenate([[0.0], np.cumsum(want)[:-1]]), 0.0)
    return np.minimum(want, left)


def net_points(lost: float, release: np.ndarray) -> np.ndarray:
    return np.maximum(lost - 100 * release / PREWAR, 0.0)


def runout(release: np.ndarray, want_any: bool, stock: float) -> int | None:
    """Calendar day the stock is used up (the first day with nothing left to release), or None."""
    used = np.cumsum(release)
    hit = np.flatnonzero(used >= stock - 1e-9)
    return int(hit[0]) + 1 if want_any and len(hit) else None


def ends(release: np.ndarray) -> int | None:
    """The first calendar day after the last release, or None if it releases nothing or to the horizon."""
    on = np.flatnonzero(release > 1e-12)
    return None if not len(on) or on[-1] == len(release) - 1 else int(on[-1]) + 1


def scenario(lost: float, policy: str, days: int, stock: float, rate: float, r26: np.ndarray) -> dict:
    """Per trading day 1..days: the release (mb/d), net points, and factor on the 2026 curve; plus the run-out
    calendar day and the total released."""
    cal = calendar_days(days)
    n = int(cal[-1]) + 1
    rel = release_path(lost, policy, n, stock, rate, r26)
    net26 = net_points(LOST_2026, r26[:n])
    assert (net26 > 0).all(), "the 2026 release replaced all the lost barrels: the curve cannot be restated"
    net = net_points(lost, rel)
    factor = np.ones(days) if lost <= 0 else LOST_2026 * net[cal] / (lost * net26[cal])
    return {"cal": cal, "release": rel[cal], "net": net[cal], "factor": factor, "release_cal": rel,
            "total_mb": float(rel.sum()), "runout": runout(rel, policy != "none" and lost > 0, stock), "ends": ends(rel)}


def factor(lost: float, policy: str = "2026", days: int = 262) -> np.ndarray:
    """Multiplier on the flow-premium curve on trading days 1..days for `lost` gross points under a release
    policy (1 everywhere for "2026"): oil_paths.premium(lost, days, z) * factor is that policy's premium."""
    stock, rate = buffer()
    cal = calendar_days(days)
    return scenario(lost, policy, days, stock, rate, release_2026(int(cal[-1]) + 1))["factor"]


def table(points=range(0, 101)) -> pd.DataFrame:
    """Every policy at every whole lost point: the 12-month mean log premium on Brent (with the curve's 90% band),
    the release, the day the stocks run out and the day the release ends."""
    stock, rate = buffer()
    c = curve(YEAR)
    cal = calendar_days(YEAR)
    r26 = release_2026(int(cal[-1]) + 1)
    rows = []
    for pol in POLICIES:
        for lost in points:
            sc = scenario(float(lost), pol, YEAR, stock, rate, r26)
            prem = {k: float((c[f"e_{k}"].values * lost * sc["factor"]).mean()) for k in ("low", "mid", "high")}
            rows.append({"policy": pol, "lost": lost, "logprem_low": prem["low"], "logprem_mid": prem["mid"],
                         "logprem_high": prem["high"],
                         "release_mean_mbd": float(sc["release"].mean()), "release_total_mb": sc["total_mb"],
                         "runout_day": sc["runout"], "end_day": sc["ends"]})
    return pd.DataFrame(rows)


# --- through the whole chain -----------------------------------------------------------------

def chain_file(policy: str) -> Path:
    """The chain's 2026-replay scenario table under a release policy (macro_chain.py replay with CHAIN_RELEASE,
    the recommended members plus margins, 2,000 draws on the same random numbers for every policy)."""
    return NOTES / f"chain-scenarios-3m-d2000-margins{'' if policy == '2026' else f'-release-{policy}'}.csv"


def chain_effects(policies=POLICIES) -> pd.DataFrame | None:
    """Each policy's change against no disruption (mean, q05, q95) per series, lost points and months ahead, in % for
    prices and points for CPI and unemployment (as the app shows them); None until the replays have run."""
    if not all(chain_file(p).exists() for p in policies):
        return None
    out = []
    for pol in policies:
        df = pd.read_csv(chain_file(pol))
        z = df[df["flow_drop_points"] == 0].set_index(["series", "months_ahead"])["mean"]
        for r in df.itertuples():
            base = z[(r.series, r.months_ahead)]
            pts = bool(re.search("cpi|unemp", r.series))
            f = (lambda x: x - base) if pts else (lambda x: (np.exp((x - base) / 100) - 1) * 100)
            out.append({"policy": pol, "series": r.series, "lost": r.flow_drop_points, "months": r.months_ahead,
                        "mean": f(r.mean), "q05": f(r.q05), "q95": f(r.q95), "unit": "points" if pts else "%"})
    return pd.DataFrame(out)


# --- country cover ---------------------------------------------------------------------------

UNITS = ("days of net imports", "days of demand", "million barrels", "days (official claim)")


def cover() -> pd.DataFrame:
    """Countries' stocks: country (as the app names it), value, unit (UNITS), as_of, basis, source, url, published."""
    df = pd.read_csv(COVER)
    assert df["country"].is_unique, "country-cover.csv: one row per country"
    assert set(df["unit"]) <= set(UNITS), f"country-cover.csv: units are {UNITS}"
    return df


def stocks_kb(value: float, unit: str, use_kbd: float, net_import_share: float) -> float | None:
    """A country's stocks in thousand barrels, from its figure in the source's own unit and the app's oil use and
    net-import share; None for an official claim, whose basis is unknown."""
    if unit == "days of net imports":
        return value * use_kbd * max(net_import_share, 0.0)
    if unit == "days of demand":
        return value * use_kbd
    if unit == "million barrels":
        return value * 1000
    return None


def days_to_replace(stocks: float | None, hormuz_kbd: float, lost: float) -> float | None:
    """Days a country's stocks (thousand barrels) would replace its lost Hormuz oil (pre-war Hormuz oil x lost
    share); inf when nothing is lost, None when the stocks are unknown."""
    if stocks is None:
        return None
    gap = hormuz_kbd * lost / 100
    return np.inf if gap <= 0 else stocks / gap


def app_countries(page: Path = ROOT / "ui" / "industry" / "index.html") -> pd.DataFrame:
    """The app's country table (oil use c, pre-war Hormuz oil h, both kb/d; net imports / use m), read from the page."""
    s = page.read_text(encoding="utf-8")
    rows = re.findall(r'"([^"]+)": \{ c: ([\d.]+), h: ([\d.]+), m: (-?[\d.]+)', s[s.index("const C = {"):])
    return pd.DataFrame(rows, columns=["country", "c", "h", "m"]).astype({"c": float, "h": float, "m": float})


# --- report ----------------------------------------------------------------------------------

def brent(logprem: float) -> float:
    return 70.0 * np.exp(logprem)  # the app's pre-war Brent (BRENT0)


def report(t: pd.DataFrame) -> list[str]:
    today = datetime.now(UTC).date().isoformat()
    tr, st = releases(), stocks()
    stock, rate = buffer()
    c = curve()
    days = len(c)
    cal = calendar_days(days)
    r26 = release_2026(int(cal[-1]) + 1, tr)
    net26 = net_points(LOST_2026, r26)
    none = scenario(LOST_2026, "none", days, stock, rate, r26)
    mx = scenario(LOST_2026, "max", days, stock, rate, r26)
    out = [
        "# Emergency oil stocks: a buffer between lost Hormuz flow and Brent",
        "",
        f"_Generated by `experiments/reserves.py` on {today}. Inputs: `notes/reserves/releases-2026.csv` (the 2026 "
        "releases), `notes/reserves/stocks.csv` (stocks held for release and how fast they can go), "
        "`notes/reserves/country-cover.csv` (stocks by country) and the flow-premium curve `notes/flow-premium.csv` "
        f"(generated {c['generated'].iloc[0]}). Every row of the CSVs carries its source, link and date. Nothing here "
        "is synthetic; the model assumptions are listed under Limits._",
        "",
        "## How the buffer works",
        "",
        "The flow-premium curve is Brent's log premium per point of *gross* lost Hormuz flow in the 2026 closure. Part "
        "of those barrels was replaced from emergency stocks, so the curve is restated per point of *net* loss "
        f"(gross minus released, in points of the pre-war {PREWAR:.0f} million barrels a day). A scenario then sets its "
        "own release: the same share of lost barrels as in 2026 (the chain as it is), none, or the IEA's maximum "
        "drawdown (up to 25 mb/d for two months, falling to nothing by six). Releases stop when the stocks held for release run out, and those barrels go missing again.",
        "",
        "## The 2026 releases",
        "",
        "| Holder | Delivery window | Million barrels | Source |",
        "|---|---|---|---|",
    ]
    for x in tr.itertuples():
        out.append(f"| {x.holder} | {x.start:%Y-%m-%d} to {x.end:%Y-%m-%d} | {x.volume_mb:,.0f} | "
                   f"[{x.source}]({x.url}), {x.published} |")
    out += ["", f"In total {tr['volume_mb'].sum():,.0f} million barrels; on the closure's busiest release day "
            f"{r26.max():.1f} million barrels a day ({100 * r26.max() / PREWAR:.0f} points of normal flow).", "",
            "| Trading day | Calendar day | Released, mb/d | Net loss, points | Premium with no release / curve |",
            "|---|---|---|---|---|"]
    for d in (1, 5, 20, 60, 120, 159, 252):
        k = d - 1
        out.append(f"| {d} | {cal[k]} | {r26[cal[k]]:.2f} | {net26[cal[k]]:.1f} | ×{none['factor'][k]:.3f} |")
    out += ["", "## Stocks held for release", "", "| Holder | Kind | Million barrels | As of | Max rate, mb/d | Counted | Source |",
            "|---|---|---|---|---|---|---|"]
    for x in st.itertuples():
        mr = "–" if pd.isna(x.max_rate_mbd) else f"{x.max_rate_mbd:g}"
        out.append(f"| {x.holder} | {x.kind} | {x.volume_mb:,.0f} | {x.as_of} | {mr} | {x.releasable} | "
                   f"[{x.source}]({x.url}), {x.published} |")
    last = "beyond the year" if mx["runout"] is None else f"{mx['runout']} days"
    out += ["", f"Counted for release: {stock:,.0f} million barrels at up to {rate:.1f} million barrels a day "
            f"combined. At 82 points lost ({0.82 * PREWAR:.1f} mb/d) and that rate, the stocks last {last}.", "",
            "## Scenarios: Brent averaged over the next 12 months", "",
            "Brent is the app's pre-war $70 times the 12-month mean premium (the curve times each day's factor).", "",
            "| Lost points | Release | Brent, mean | 90% range | Released, mean mb/d | Released, total mb | Stocks run out | Release ends |",
            "|---|---|---|---|---|---|---|---|"]
    for lost in (25, 50, 82, 100):
        for pol in POLICIES:
            r = t[(t["lost"] == lost) & (t["policy"] == pol)].iloc[0]
            ro = "–" if pd.isna(r["runout_day"]) else f"day {int(r['runout_day'])}"
            en = "–" if pd.isna(r["end_day"]) else f"day {int(r['end_day'])}"
            out.append(f"| {lost} | {pol} | ${brent(r['logprem_mid']):.0f} | ${brent(r['logprem_low']):.0f}–"
                       f"${brent(r['logprem_high']):.0f} | {r['release_mean_mbd']:.2f} | "
                       f"{r['release_total_mb']:,.0f} | {ro} | {en} |")
    ce = chain_effects()
    out += ["", "## Through the whole chain", ""]
    if ce is None:
        out += ["The chain's replays under each policy have not been run yet (`CHAIN_RELEASE=none` and `max`; see "
                "`docs/chain.md`)."]
    else:
        out += ["The 2026 replay of the recommended chain (`bayes_own` + `global_lin` + `global`, margin member on the "
                "fuels), run on Iridis once per policy with 2,000 draws on the same random numbers "
                "(`notes/chain-scenarios-3m-d2000-margins*.csv`). Change against no disruption: mean and 90% range, % for "
                "prices and points for CPI. The app shows the published table (`notes/chain-scenarios-3m-margins.csv`, "
                "400 draws) plus each policy's difference from the 2026 run here.", "",
                "| Series | Lost points | Months | As in 2026 | No release | IEA maximum |", "|---|---|---|---|---|---|"]
        names = {"us_cpi": "US CPI", "uk_cpi": "UK CPI", "ea_cpi": "Euro-area HICP", "ind_gasdesw": "US diesel at the pump",
                 "ind_djfuelusgulf": "Jet fuel (US Gulf)"}
        for sname, nm in names.items():
            for lost in (50, 82, 100):
                for mo in (3, 12):
                    cells = []
                    for pol in POLICIES:
                        r = ce[(ce.policy == pol) & (ce.series == sname) & (ce.lost == lost) & (ce.months == mo)].iloc[0]
                        cells.append(f"{r['mean']:+.1f} ({r['q05']:+.1f} to {r['q95']:+.1f})")
                    out.append(f"| {nm} | {lost} | {mo} | " + " | ".join(cells) + " |")
        g = lambda pol, sn, mo: float(ce[(ce.policy == pol) & (ce.series == sn) & (ce.lost == 82) & (ce.months == mo)]["mean"].iloc[0])  # noqa: E731
        d = {(pol, sn, mo): g(pol, sn, mo) - g("2026", sn, mo) for pol in ("none", "max")
             for sn in ("ind_gasdesw", "us_cpi") for mo in (3, 12)}
        out += ["", f"At 82 points lost, against the chain as in 2026: with no release, diesel's rise is "
                f"{d['none', 'ind_gasdesw', 3]:+.1f} points after 3 months and {d['none', 'ind_gasdesw', 12]:+.1f} after 12, and "
                f"US CPI {d['none', 'us_cpi', 3]:+.2f} and {d['none', 'us_cpi', 12]:+.2f} points. The 2026 releases came "
                f"early and were small next to the lost barrels, so they moved the chain a little. At the IEA's maximum, "
                f"diesel is {d['max', 'ind_gasdesw', 3]:+.1f} points after 3 months and US CPI {d['max', 'us_cpi', 3]:+.2f} while "
                f"the stocks last; once they are spent ({mx['runout']} days) prices catch up, and by month 12 the gaps are "
                f"{d['max', 'ind_gasdesw', 12]:+.1f} and {d['max', 'us_cpi', 12]:+.2f}. The Brent averages above include those "
                f"early months, so they move more than the 12-month knock-ons do."]
    cv, app = cover(), app_countries()
    m = cv.merge(app, on="country", how="left")
    out += ["", "## Stock cover by country", "",
            "Each country's stocks in its source's own unit, and how long they alone would replace the oil it "
            "received through Hormuz before the war, at 82 points lost. The IEA counts days of the previous year's "
            "net imports; our JODI figures are crude and product stocks over product demand; the two are not "
            "comparable, and an official claim is shown but not used. Oil use, Hormuz oil and net imports come from "
            "the app's country table (`ui/industry/index.html`).", "",
            "| Country | Stocks | Basis | As of | Replace lost Hormuz oil at 82 points, days | Source |",
            "|---|---|---|---|---|---|"]
    for x in m.itertuples():
        kb = None if pd.isna(x.c) else stocks_kb(x.value, x.unit, x.c, x.m)
        rep = days_to_replace(kb, x.h, LOST_2026) if not pd.isna(x.h) and x.h > 0 else None
        out.append(f"| {x.country} | {x.value:,.0f} {x.unit} | {x.basis} | {x.as_of} | "
                   f"{'–' if rep is None else f'{rep:,.0f}'} | [{x.source}]({x.url}), {x.published} |")
    out += ["", "## Limits", "",
            "- **The lost flow itself.** The curve's 82 points come from IMF PortWatch's AIS tanker counts, which show "
            "Hormuz near 0-2% of normal for most of the closure. The IEA puts flows through the strait at 2.7 mb/d over "
            "March-May (about 86 points lost; [commentary, 22 Jun 2026](https://www.iea.org/commentaries/how-global-oil-"
            "supplies-have-readjusted-to-help-fill-the-huge-gap-left-by-the-strait-of-hormuz-shock)) but 10.9 mb/d in "
            "September, helped by ship-to-ship transfers (about 45 points; [Oil Market Report, 14 Oct 2026](https://www."
            "iea.org/reports/oil-market-report-october-2026)). If the IEA is right, the loss shrank over the summer "
            "while the curve holds it at 82, so the late-closure premium per point is understated. That is a question "
            "for the flow estimate; it does not change how the stocks enter.",
            "- **Proportional premium (assumption).** Brent's premium is taken to scale with the net barrels missing. "
            "One closure cannot test that: the curve still rests on 2026, and the release only reweights it.",
            "- **Bypass pipelines** stay inside the curve as they were in 2026; they are not a separate offset here.",
            "- **Delivery windows.** Each tranche is spread evenly over its window; actual loadings were lumpier.",
            "- **Maximum rate and run-out.** A release at the maximum rate assumes every counted holder draws at once. "
            "In practice stocks are drawn more slowly near the bottom, and a run-out comes with a price spike this "
            "curve does not model.",
            "- **Country cover** treats all of a country's stocks as usable for its lost Hormuz oil; the legal "
            "minimum, product mix and refinery fit all cut that in practice.",
            ""]
    return out


def write_table(t: pd.DataFrame) -> None:
    out = t.copy()
    for k in ("logprem_low", "logprem_mid", "logprem_high", "release_mean_mbd", "release_total_mb"):
        out[k] = out[k].round(6)
    out["runout_day"] = out["runout_day"].astype("Int64")
    out["end_day"] = out["end_day"].astype("Int64")
    out["source"] = "experiments/reserves.py on notes/flow-premium.csv and notes/reserves/*.csv"
    out["generated"] = datetime.now(UTC).date().isoformat()
    out.to_csv(TABLE, index=False)


def main() -> None:
    t = table()
    write_table(t)
    OUT.write_text("\n".join(report(t)), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    print(OUT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
