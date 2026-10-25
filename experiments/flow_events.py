# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "xlrd>=2.0", "openpyxl>=3.1"]
# ///
"""Out-of-sample checks of the chain's flow -> Brent link, and a premium curve with a band.

The chain's premium (experiments/oil_paths.py) rests on one event, the 2026 Hormuz closure
(notes/flow-price-link.md). Here the same measurement is made on other chokepoint disruptions that
IMF PortWatch shows from 2019 to 2025, found by a rule fixed from the flow data alone, before
Brent around any event was looked at:

- flow: the 7-day mean of daily tanker capacity through the chokepoint as a share of its 2019-2024
  average (as flow_price.daily_flow)
- an event starts on the first day the 7-day share is at least DROP below its pre-level (the mean
  over days -29..-7, flow_price's pre-closure level) and stays there for SUSTAIN days running; a
  later start at the same chokepoint counts only GAP days on, so one episode gives one event
- lost flow at horizon h: the pre-level minus the mean 7-day share from day 0 to trading day h, in
  points of that chokepoint's normal flow
- Brent: the log change from 5 trading days before day 0 to trading days +5, +20, +60, +120, per
  point of lost flow (as flow_price's event study)
- placebo: the same change from every other trading day of 2019-2025 (more than EXCLUDE trading
  days from an event or a dated disruption, window ending before the 2026 closure), divided by
  the event's lost flow: the noise band of the per-point number
- rerouting: Cape of Good Hope transits gained over the same window, in Bab el-Mandeb points,
  separate rerouted barrels from barrels that went missing
- bypass: tanker exports from Yanbu and Fujairah (the pipelines' sea ends) against exports from
  ports inside the Gulf (macro_data's pipeline block) give the share of the Gulf's lost exports
  the pipelines replaced during the 2026 closure

Events are tagged against a list of dated disruptions (NEWS) written down with the rule. Dated
disruptions the rule does not find are reported unscaled: Brent's move with little or no flow
lost, which is the risk premium alone.

The premium curve (notes/flow-premium.csv) is the 2026 closure's daily path per point of lost
flow, smoothed by a jump-ramp-decay-plateau curve fitted to every observed day, with a 90% band
from the placebo noise of a single event; after the last observed day it is an assumption.

That curve divides Brent by PortWatch's trough, 82 points lost for the whole closure. PortWatch
counts AIS-visible tankers only; the IEA's monthly estimates of oil through the strait
(notes/hormuz-iea-flows.csv, each figure with its report and date) also count dark transits and
Gulf of Oman ship-to-ship transfers. `iea` refits the curve per point of the IEA's lost flow, day
by day, and leaves notes/flow-premium.csv alone.

    uv run experiments/flow_events.py   # writes notes/flow-events.md and notes/flow-premium.csv
    uv run experiments/flow_events.py iea [--out DIR]   # notes/hormuz-flow-check.md, notes/flow-premium-iea.csv
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import numpy as np
import pandas as pd

import flow_price as fp
import macro_data as md

OUT = md.ROOT / "notes" / "flow-events.md"
CURVE = md.ROOT / "notes" / "flow-premium.csv"
IEA_FLOWS = md.ROOT / "notes" / "hormuz-iea-flows.csv"  # IEA figures for oil through the strait, one source per row
IEA_OUT, IEA_CURVE = "hormuz-flow-check.md", "flow-premium-iea.csv"  # written to notes/ (or --out)
HORMUZ, BABEL, CAPE = "chokepoint6", "chokepoint4", "chokepoint7"
PORTS = {HORMUZ: "Strait of Hormuz", BABEL: "Bab el-Mandeb", CAPE: "Cape of Good Hope"}
BYPASS = "port570,port362"  # Yanbu (East-West pipeline), Fujairah (Habshan-Fujairah pipeline)
GULF = "port526,port1091,port2479,port24,port512,port2237,port1341"  # macro_data's gulf_exports

# The event rule (fixed from the flow data before looking at Brent around any event).
SMOOTH = 7  # days in the rolling mean of the daily flow share
DROP = 0.25  # the 7-day share must fall at least 25 points of normal below its pre-level ...
SUSTAIN = fp.SUSTAIN  # ... and stay there for 14 days running
PRE = (29, 7)  # pre-level: mean 7-day share over days t-29..t-7, as flow_price
GAP = pd.Timedelta(days=182)  # a new event at one chokepoint needs half a year (> 120 trading days)
WINDOW = ("2019-02-01", "2025-12-31")  # out of sample: before the 2026 closure
CLOSURE = pd.Timestamp("2026-02-01")  # out-of-sample and placebo windows end before this
HORIZONS = (5, 20, 60, 120)
BASE_LAG = 5  # Brent's change is against 5 trading days before day 0
EXCLUDE = 20  # placebo days are more than this many trading days from any event's day 0
MIN_LOST = 5.0  # points: below this the per-point number is not reported (the flow came back)
NEWS_MATCH = (-45, 14)  # an event is news-matched if a dated disruption falls this many days around day 0
Q = (0.05, 0.95)  # the placebo band

# Dated disruptions, from news reports, listed by hand with the rule (not read from Brent).
NEWS = [
    (HORMUZ, "2019-05-12", "Sabotage of four tankers off Fujairah"),
    (HORMUZ, "2019-06-13", "Attacks on two tankers in the Gulf of Oman"),
    (HORMUZ, "2019-07-19", "Iran seizes the tanker Stena Impero in the strait"),
    (HORMUZ, "2019-09-14", "Attack on Abqaiq and Khurais (Saudi processing, not the strait)"),
    (HORMUZ, "2020-01-03", "US strike kills Qasem Soleimani"),
    (HORMUZ, "2024-04-13", "Iran seizes the MSC Aries near the strait and attacks Israel"),
    (HORMUZ, "2025-06-13", "Israel strikes Iran (the twelve-day war)"),
    (BABEL, "2023-11-19", "Houthis seize the Galaxy Leader"),
    (BABEL, "2023-12-18", "BP and the big container lines pause Red Sea transits"),
    (BABEL, "2024-01-12", "US and UK strikes on the Houthis"),
]

# The premium curve.
CURVE_DAYS = 262  # the most trading days in 12 months (oil_paths.premium's horizon)
D_PEAK_GRID = range(3, 41)
HALF_LIFE_GRID = np.r_[np.arange(2, 40, 1), np.arange(40, 400, 5)]
# oil_paths.premium as of commit 1b66286, for comparison (not imported: oil_paths pulls in torch)
OP_E_PEAK, OP_E_LATE, OP_D_PEAK, OP_D_LATE = np.log(1.67) / 82.0, np.log(1.222) / 82.0, 20, 120


# --- flows -----------------------------------------------------------------------------------

def portwatch_daily(port: str, field: str = "capacity_tanker") -> pd.Series:
    """A daily PortWatch field for one chokepoint (capacity_tanker, n_tanker), from the cache
    macro_data keeps."""
    md.fetch_portwatch(f"{port}:{field}")  # make sure the cache exists
    df = pd.DataFrame(json.loads((md.RAW / f"portwatch_{port}.json").read_text(encoding="utf-8")))
    dates = pd.to_datetime(df["date"], unit="ms") if pd.api.types.is_numeric_dtype(df["date"]) \
        else pd.to_datetime(df["date"])
    return pd.Series(df[field].astype(float).values, index=dates).sort_index().asfreq("D")


def load_flow(port: str) -> tuple[pd.Series, float]:
    """Daily tanker capacity through a chokepoint as a share of its 2019-2024 mean, and that mean
    (deadweight tonnes a day)."""
    s = portwatch_daily(port)
    base = s.loc[md.SHARE_BASE[0]:md.SHARE_BASE[1]].mean()
    return s / base, float(base)


def port_exports(code: str) -> pd.Series:
    """Daily tanker exports (tonnes) summed over a group of PortWatch ports."""
    md.fetch_ports(code)  # make sure the cache exists
    path = md.RAW / f"portwatch_ports_{code.replace(',', '_')}.json"
    df = pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
    df["date"] = pd.to_datetime(df["date"], unit="ms") if pd.api.types.is_numeric_dtype(df["date"]) \
        else pd.to_datetime(df["date"])
    return df.groupby("date")["export_tanker"].sum().astype(float).asfreq("D")


def smooth(share: pd.Series) -> pd.Series:
    return share.rolling(SMOOTH).mean()


def pre_level(s: pd.Series) -> pd.Series:
    """Mean of the smoothed share over days t-29..t-7 (flow_price's pre-closure level)."""
    return s.shift(PRE[1]).rolling(PRE[0] - PRE[1] + 1).mean()


def find_events(s: pd.Series, start=WINDOW[0], end=WINDOW[1], drop=DROP, sustain=SUSTAIN,
                gap=GAP) -> list[pd.Timestamp]:
    """Event starts in [start, end]: days the smoothed daily share s falls at least `drop` below
    its pre-level and stays there (against that same pre-level) for `sustain` days, `gap` apart."""
    ahead = s[::-1].rolling(sustain).max()[::-1].reindex(s.index)  # max of s over t..t+sustain-1
    hit = (ahead < pre_level(s) - drop) & (s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))
    events: list[pd.Timestamp] = []
    for t in hit[hit].index:
        if not events or t - events[-1] >= gap:
            events.append(t)
    return events


def closure_start(s: pd.Series) -> pd.Timestamp:
    """flow_price's rule for the 2026 closure: the first day from June 2025 the 7-day share stays
    below 50% for SUSTAIN days."""
    sustained = (s < 0.5).astype(int).rolling(SUSTAIN).min().shift(-(SUSTAIN - 1)) == 1
    return sustained.loc["2025-06-01":][lambda x: x].index.min()


def shortfall(s: pd.Series, t0, t1, pre: float | None = None) -> float:
    """Points of normal flow lost from t0 to t1: the pre-level at t0 minus the mean share."""
    pre = pre_level(s).loc[t0] if pre is None else pre
    return 100 * (pre - s.loc[t0:t1].mean())


def bypass_offset(byp: pd.Series, gulf: pd.Series, t0, t1, a=None) -> float:
    """Share of the Gulf ports' lost exports that the bypass ports made up from a (default t0) to
    t1, both against their pre-levels at t0 (smoothed series)."""
    a = t0 if a is None else a
    gain = byp.loc[a:t1].mean() - pre_level(byp).loc[t0]
    loss = pre_level(gulf).loc[t0] - gulf.loc[a:t1].mean()
    return float(gain / loss)


# --- Brent -----------------------------------------------------------------------------------

def brent_daily() -> pd.Series:
    """Daily Brent spot, the FRED file flow_price and oil_paths read."""
    df = pd.read_csv(md.RAW / "fred_DCOILBRENTEU.csv", parse_dates=["observation_date"])
    return pd.Series(pd.to_numeric(df["DCOILBRENTEU"], errors="coerce").values, index=df["observation_date"]).dropna()


def day0(brent: pd.Series, t) -> int:
    """Position of the first trading day on or after calendar day t."""
    return int(brent.index.searchsorted(pd.Timestamp(t)))


def moves(brent: pd.Series, i0: int, horizons=HORIZONS) -> np.ndarray:
    """Brent's log change from BASE_LAG trading days before position i0 to each horizon after it."""
    base = brent.iloc[i0 - BASE_LAG]
    return np.array([np.log(brent.iloc[i0 + h] / base) if i0 + h < len(brent) else np.nan for h in horizons])


def placebo(brent: pd.Series, events: list[int], lo=WINDOW[0], hi=CLOSURE, horizons=HORIZONS,
            exclude=EXCLUDE) -> np.ndarray:
    """Brent's moves [n, len(horizons)] from every trading day from `lo` whose longest window ends
    before `hi` and that is more than `exclude` trading days from each event position."""
    pos = np.arange(max(day0(brent, lo), BASE_LAG), day0(brent, hi) - max(horizons))
    for e in events:
        pos = pos[np.abs(pos - e) > exclude]
    return np.array([moves(brent, i, horizons) for i in pos])


def per_point(move: float, lost: float) -> float:
    """% of Brent per point of lost flow (nan when too little flow was lost to scale by)."""
    return 100 * move / lost if lost >= MIN_LOST else np.nan


def placebo_band(noise: np.ndarray, lost: float, q=Q) -> tuple[float, float]:
    """The q-quantiles of placebo moves scaled by the event's lost flow, in % of Brent per point."""
    if lost < MIN_LOST:
        return np.nan, np.nan
    lo, hi = np.quantile(100 * noise / lost, q)
    return float(lo), float(hi)


def news_for(port: str, t0: pd.Timestamp) -> str:
    hits = [f"{d}: {what}" for p, d, what in NEWS if p == port
            and NEWS_MATCH[0] <= (pd.Timestamp(d) - t0).days <= NEWS_MATCH[1]]
    return "; ".join(hits)


# --- the premium curve -----------------------------------------------------------------------

def curve_shape(d: np.ndarray, jump: float, peak: float, d_peak: int, half_life: float,
                plateau: float) -> np.ndarray:
    """Log premium per point on trading day d: a jump on day 1 rising linearly to the peak on
    d_peak, then an exponential decay with the given half-life to a plateau."""
    w = np.exp(-np.log(2) / half_life * np.clip(d - d_peak, 0, None))
    return np.where(d <= d_peak, jump + (peak - jump) * d / d_peak, plateau + (peak - plateau) * w)


def fit_curve(y: np.ndarray, weights: np.ndarray | None = None, decay_only: bool = True) -> dict:
    """Least squares fit of curve_shape to a daily path y (days 1..len(y)): a grid over d_peak and
    the half-life, with jump, peak and plateau linear given those two. weights: one per day for a
    weighted fit (scaled to mean 1, so the rmse stays in y's units); none weights days equally.
    decay_only: the plateau may not exceed the peak, so the tail decays as the shape says (a long
    half-life towards a higher plateau would be a slow rise instead)."""
    d = np.arange(1, len(y) + 1, dtype=float)
    sw = np.ones(len(y)) if weights is None else np.sqrt(np.asarray(weights, float) / np.mean(weights))
    best = None
    for dp in D_PEAK_GRID:
        for hl in HALF_LIFE_GRID:
            w = np.exp(-np.log(2) / hl * np.clip(d - dp, 0, None))
            X = np.column_stack([np.where(d <= dp, 1 - d / dp, 0), np.where(d <= dp, d / dp, w),
                                 np.where(d <= dp, 0, 1 - w)])
            b, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
            if decay_only and b[2] > b[1]:  # the best decay is then flat from the peak (plateau = peak)
                b2, *_ = np.linalg.lstsq(np.column_stack([X[:, 0], X[:, 1] + X[:, 2]]) * sw[:, None], y * sw, rcond=None)
                b = np.array([b2[0], b2[1], b2[1]])
            sse = float((((y - X @ b) * sw) ** 2).sum())
            if best is None or sse < best["sse"]:
                best = {"jump": b[0], "peak": b[1], "d_peak": dp, "half_life": float(hl), "plateau": b[2], "sse": sse}
    best["rmse"] = np.sqrt(best["sse"] / len(y))
    return best


def premium_curve(y: np.ndarray, noise: np.ndarray, lost, days: int = CURVE_DAYS) -> pd.DataFrame:
    """e_low, e_mid, e_high per trading day 1..days (log premium per point of lost flow): e_mid is
    the fit to the observed path y, held at its value on the last observed day after that (an
    assumption); the band adds the placebo's centred 5% and 95% moves at each horizon divided by
    the event's lost flow (the error of a one-event estimate), with the low edge floored at zero.
    noise: [n, days]. lost: one number, or one per observed day (y is then Brent's move divided by
    each day's loss); a path weights each day by lost² in the fit, so it fits the move itself
    (move ≈ lost × curve, Brent's noise being the same each day), and is held at its last value
    for the band beyond the observed days."""
    path, lost = np.ndim(lost) > 0, np.asarray(lost, float)
    p = fit_curve(y, lost ** 2 if path else None)
    d = np.arange(1, days + 1, dtype=float)
    mid = curve_shape(d, p["jump"], p["peak"], p["d_peak"], p["half_life"], p["plateau"])
    mid[len(y):] = mid[len(y) - 1]
    q = np.quantile(noise, [Q[0], 0.5, Q[1]], axis=0)
    scale = np.r_[lost, np.full(days - len(y), lost[-1])] if path else lost
    low = np.maximum(mid + (q[0] - q[1]) / scale, 0.0)
    high = mid + (q[2] - q[1]) / scale
    return pd.DataFrame({"trading_day": d.astype(int), "e_low": low, "e_mid": mid, "e_high": high,
                         "observed": d <= len(y)}), p


def chain_premium(days: int = CURVE_DAYS) -> np.ndarray:
    """oil_paths.premium(1, days) as of commit 1b66286: the chain's current curve per point."""
    d = np.arange(1, days + 1, dtype=float)
    k = np.log(OP_E_PEAK / OP_E_LATE) / (OP_D_LATE - OP_D_PEAK)
    return np.where(d <= OP_D_PEAK, OP_E_PEAK * d / OP_D_PEAK,
                    np.where(d <= OP_D_LATE, OP_E_PEAK * np.exp(-k * (d - OP_D_PEAK)), OP_E_LATE))


# --- the IEA's lost flow ---------------------------------------------------------------------

def iea_figures(path=IEA_FLOWS) -> pd.DataFrame:
    """Every IEA figure in the sourced table (period, measure, mb_d, counts, statement, source, url,
    published, used)."""
    return pd.read_csv(path, dtype=str).assign(mb_d=lambda x: x["mb_d"].astype(float))


def iea_monthly(figs: pd.DataFrame) -> pd.DataFrame:
    """The rows marked used, one per month and measure (strait, bypass), mb/d by calendar month."""
    use = figs[figs["used"] == "yes"]
    if use.duplicated(["period", "measure"]).any():
        raise ValueError("hormuz-iea-flows.csv: two used rows for one month and measure")
    out = use.pivot(index="period", columns="measure", values="mb_d")
    out.index = pd.PeriodIndex(out.index, freq="M")
    return out.sort_index()


def iea_lost(dates, strait: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Points of pre-war strait flow lost on each date, 100 × (1 − the month's flow / the first
    month's), the first month (February 2026) being the IEA's last before the war; and whether the
    date is past the last month with a figure, where that month's flow is held (an assumption)."""
    months = pd.DatetimeIndex(dates).to_period("M")
    if (months < strait.index[0]).any():
        raise ValueError("a date before the IEA's pre-war month")
    held = np.asarray(months > strait.index[-1])
    flow = strait.reindex([min(m, strait.index[-1]) for m in months]).to_numpy()
    if np.isnan(flow).any():
        raise ValueError("a month with no IEA figure before the last one")
    return 100 * (1 - flow / strait.iloc[0]), held


# --- the study -------------------------------------------------------------------------------

def study() -> dict:
    brent = brent_daily()
    flows = {p: load_flow(p) for p in PORTS}
    sm = {p: smooth(flows[p][0]) for p in PORTS}
    ratio = {p: flows[p][1] / flows[HORMUZ][1] for p in PORTS}  # one point here, in Hormuz points
    closed = day0(brent, CLOSURE)

    found = []
    for port in (HORMUZ, BABEL):
        for t0 in find_events(sm[port]):
            i0 = day0(brent, t0)
            ends = [brent.index[min(i0 + h, len(brent) - 1)] for h in HORIZONS]
            ev = {"port": port, "t0": t0, "i0": i0, "news": news_for(port, t0), "clean": i0 + max(HORIZONS) < closed,
                  "pre": float(pre_level(sm[port]).loc[t0]),
                  "lost": np.array([shortfall(sm[port], t0, t1) for t1 in ends]), "move": moves(brent, i0)}
            if port == BABEL:  # Cape gain over the same window, in Bab el-Mandeb points
                gain = np.array([-shortfall(sm[CAPE], t0, t1) for t1 in ends]) * ratio[CAPE] / ratio[BABEL]
                ev["rerouted"] = np.clip(gain, 0, ev["lost"])
            else:
                ev["rerouted"] = np.zeros(len(HORIZONS))
            ev["net"] = ev["lost"] - ev["rerouted"]
            found.append(ev)

    dated = []
    for port, d, what in NEWS:
        t0 = pd.Timestamp(d)
        i0 = day0(brent, t0)
        t20 = brent.index[i0 + 20]
        dated.append({"port": port, "date": d, "what": what, "i0": i0, "move": moves(brent, i0, (0,) + HORIZONS),
                      "lost20": shortfall(sm[port], t0, t20),
                      "rule": any(e["port"] == port and abs((e["t0"] - t0).days) <= 45 for e in found)})

    noise0 = placebo(brent, [e["i0"] for e in found] + [x["i0"] for x in dated], horizons=(0,) + HORIZONS)
    noise = noise0[:, 1:]

    # The 2026 closure: flow_price's start and lost flow (the chain's LOST_2026), and the same
    # measures as the events above.
    h = sm[HORMUZ]
    start = closure_start(h)
    i26 = day0(brent, start)
    pre26 = float(h.loc[:start].iloc[-30:-7].mean())
    lost26 = 100 * (pre26 - h.loc[start:start + pd.Timedelta(days=90)].min())
    obs = len(brent) - 1 - i26  # trading days observed after day 0
    path = moves(brent, i26, tuple(range(1, obs + 1))) / lost26  # log premium per point, days 1..obs
    ends26 = [brent.index[min(i26 + hh, len(brent) - 1)] for hh in HORIZONS]
    byp, gulf = smooth(port_exports(BYPASS)), smooth(port_exports(GULF))
    blocks = []
    for a in range(1, obs + 1, 21):
        b = min(a + 20, obs)
        ta, tb = brent.index[i26 + a], brent.index[i26 + b]
        gross = shortfall(h, ta, tb, pre26)
        off = bypass_offset(byp, gulf, start, tb, a=ta)
        blocks.append({"a": a, "b": b, "ta": ta, "tb": tb, "share": h.loc[ta:tb].mean(), "gross": gross,
                       "peak_share": h.loc[ta:tb].max(),
                       "gulf_lost": 1 - gulf.loc[ta:tb].mean() / pre_level(gulf).loc[start],
                       "offset": off, "move": float(np.mean(moves(brent, i26, tuple(range(a, b + 1)))))})
    closure = {"start": start, "i0": i26, "pre": pre26, "lost": lost26, "obs": obs, "path": path,
               "day0": float(moves(brent, i26, (0,))[0]), "share_0": float(h.loc[brent.index[i26]]),
               "share_m5": float(h.loc[brent.index[i26 - BASE_LAG]]),
               "lost_h": np.array([shortfall(h, start, t1, pre26) for t1 in ends26]),
               "move": moves(brent, i26), "blocks": blocks,
               "offset_all": bypass_offset(byp, gulf, start, brent.index[i26 + obs])}

    long_noise = placebo(brent, [e["i0"] for e in found] + [x["i0"] for x in dated], horizons=tuple(range(1, CURVE_DAYS + 1)))
    curve, fit = premium_curve(path, long_noise, lost26)
    return {"brent": brent, "flows": flows, "sm": sm, "ratio": ratio, "events": found, "dated": dated,
            "noise": noise, "noise0": noise0, "long_noise": long_noise, "closure": closure, "curve": curve, "fit": fit}


def refit_iea(r: dict) -> dict:
    """The 2026 curve refitted per point of lost flow day by day: the IEA's monthly path, and for
    comparison PortWatch's own daily path (its 7-day share against the 82% pre-level) and the IEA's
    mean loss to date (a premium that follows cumulative barrels), instead of PortWatch's trough
    held for the whole closure. Same Brent path, same placebo. iea_free: the IEA fit with the tail
    left free to rise (reported, not used)."""
    brent, cl = r["brent"], r["closure"]
    figs = iea_figures()
    monthly = iea_monthly(figs)
    days = brent.index[cl["i0"] + 1:cl["i0"] + cl["obs"] + 1]  # trading days 1..obs
    move = cl["path"] * cl["lost"]  # Brent's log change from 5 trading days before day 0
    lost, held = iea_lost(days, monthly["strait"])
    sm = r["sm"][HORMUZ].dropna().reindex(days, method="ffill")  # PortWatch can end a few days before Brent
    lost_pw = np.maximum(100 * (cl["pre"] - sm.to_numpy()), MIN_LOST)
    to_date = np.cumsum(lost) / np.arange(1, len(lost) + 1)
    out = {"figs": figs, "monthly": monthly, "days": days, "move": move, "held": held}
    for key, l in (("iea", lost), ("pw_daily", lost_pw), ("iea_to_date", to_date)):
        curve, fit = premium_curve(move / l, r["long_noise"], l)
        fit["rms_move"] = float(np.sqrt(np.mean((move - l * curve["e_mid"].values[:len(l)]) ** 2)))
        lost_h = np.array([l[h - 1] for h in HORIZONS])
        out[key] = {"lost": l, "path": move / l, "curve": curve, "fit": fit, "lost_h": lost_h, "e26": cl["move"] / lost_h}
    free = fit_curve(move / lost, lost ** 2, decay_only=False)
    e = curve_shape(np.arange(1, len(lost) + 1, dtype=float), *(free[k] for k in ("jump", "peak", "d_peak", "half_life", "plateau")))
    free["rms_move"], free["e_last"] = float(np.sqrt(np.mean((move - lost * e) ** 2))), float(e[-1])
    out["iea_free"] = {"lost": lost, "fit": free}
    r["fit"]["rms_move"] = float(np.sqrt(np.mean((move - cl["lost"] * r["curve"]["e_mid"].values[:cl["obs"]]) ** 2)))
    return out


# --- report ----------------------------------------------------------------------------------

def fetched(name: str) -> str:
    return datetime.fromtimestamp((md.RAW / name).stat().st_mtime, UTC).date().isoformat()


def f(x: float, fmt: str = "+.2f") -> str:
    return "n/a" if not np.isfinite(x) else format(x, fmt)


def report(r: dict) -> list[str]:
    today = datetime.now(UTC).date().isoformat()
    brent, noise, cl, ratio = r["brent"], r["noise"], r["closure"], r["ratio"]
    curve, fit = r["curve"], r["fit"]
    pq = np.quantile(noise, [Q[0], 0.5, Q[1]], axis=0)
    hpos = {h: k for k, h in enumerate(HORIZONS)}
    cleans = [e for e in r["events"] if e["clean"]]
    real = [e for e in cleans if e["news"]]
    out = [
        "# Flow → Brent out of sample: other chokepoint disruptions, and a premium curve with a band",
        "",
        f"_Generated by `experiments/flow_events.py` on {today}. Flow: IMF PortWatch daily tanker capacity through "
        f"the Strait of Hormuz, Bab el-Mandeb and the Cape of Good Hope (AIS-derived, fetched {fetched('portwatch_chokepoint6.json')}), "
        f"{r['flows'][HORMUZ][0].index[0]:%Y-%m-%d} to {r['flows'][HORMUZ][0].index[-1]:%Y-%m-%d}, as a share of each "
        f"chokepoint's 2019–2024 average; PortWatch daily port exports for the pipeline bypass (fetched "
        f"{fetched('portwatch_ports_port570_port362.json')}). Brent: FRED DCOILBRENTEU (fetched "
        f"{fetched('fred_DCOILBRENTEU.csv')}), to {brent.index[-1]:%Y-%m-%d}. The caches were copied from another checkout "
        "of this repository; nothing was downloaded again. Dates of disruptions: news reports, listed by hand. "
        "Nothing here is synthetic._",
        "",
    ]

    # Summary.
    k20, k120 = hpos[20], hpos[120]
    pts = [100 * b["move"] / b["gross"] for b in cl["blocks"]]
    lo_b, hi_b = cl["blocks"][int(np.argmin(pts))], cl["blocks"][int(np.argmax(pts))]
    pq0 = np.quantile(r["noise0"], [Q[0], 0.5, Q[1]], axis=0)  # horizon 0 first, then HORIZONS
    out += ["## Summary", "", "Brent changes are log changes in %, from 5 trading days before day 0.", ""]
    for e in real:
        lo20, hi20 = placebo_band(noise[:, k20], e["lost"][k20])
        lo120, hi120 = placebo_band(noise[:, k120], e["lost"][k120])
        pp20, pp120 = per_point(e["move"][k20], e["lost"][k20]), per_point(e["move"][k120], e["lost"][k120])
        within = lambda x, lo, hi: "inside" if lo <= x <= hi else "outside"  # noqa: E731
        out.append(
            f"- **Out-of-sample disruption: {PORTS[e['port']]}, day 0 {e['t0']:%Y-%m-%d}.** {e['lost'][k20]:.0f} points of "
            f"that strait's normal tanker flow lost by +20 trading days and {e['lost'][k120]:.0f} by +120. Brent moved "
            f"{100 * e['move'][k20]:+.1f}% and {100 * e['move'][k120]:+.1f}%: {pp20:+.2f}% and {pp120:+.2f}% per point, "
            f"{within(pp20, lo20, hi20)} the placebo band at +20 ({lo20:+.2f} to {hi20:+.2f}) and "
            f"{within(pp120, lo120, hi120)} it at +120 ({lo120:+.2f} to {hi120:+.2f}).")
        conv = ratio[e["port"]]
        g20, g120 = e["lost"][k20] * conv, e["lost"][k120] * conv
        n20, n120 = e["net"][k20] * conv, e["net"][k120] * conv
        e26 = cl["move"] / cl["lost"]
        span = pq[:, [k20, k120]] - pq[1, [k20, k120]]
        fits = all(e26[k] * e["lost"][k] * conv + span[0, j] <= e["move"][k] <= e26[k] * e["lost"][k] * conv + span[2, j]
                   for j, k in enumerate((k20, k120)))
        out.append(
            f"  The Cape gained {e['rerouted'][k120]:.0f} of the {e['lost'][k120]:.0f} points by +120 days "
            f"({e['rerouted'][k120] / e['lost'][k120]:.0%} rerouted). In Hormuz tonnage (one point here is {conv:.2f} Hormuz "
            f"points) that is {g20:.0f} and {g120:.0f} Hormuz points gross, {n20:.0f} and {n120:.0f} net of rerouting: "
            f"{per_point(e['move'][k20], g20):+.2f}% and {per_point(e['move'][k120], g120):+.2f}% per gross point, "
            f"{per_point(e['move'][k20], n20):+.2f}% and {per_point(e['move'][k120], n120):+.2f}% per net point, against "
            f"{100 * e26[k20]:+.2f}% and {100 * e26[k120]:+.2f}% for the 2026 closure. The 2026 response scaled to this "
            f"event's loss {'predicts' if fits else 'misses'} its Brent move within Brent's own noise at both horizons.")
    nonews = [e for e in cleans if not e["news"]]
    rally = [e for e in nonews if (noise[:, k20] >= e["move"][k20]).mean() <= 0.05]
    winter = r["flows"][HORMUZ][0].resample("QS").mean().loc["2019-01":"2021-01"]
    winter = winter[winter.index.month.isin((1, 10))]
    out.append(
        f"- **Dips with no disruption behind them.** The rule also finds {len(nonews)} dips that no dated disruption "
        "matches (" + ", ".join(f"{PORTS[e['port']]} {e['t0']:%Y-%m-%d}" for e in nonews) + "). PortWatch's Hormuz share "
        f"sat at {winter.min():.0%}–{winter.max():.0%} of normal in the winter quarters from 2019 to early 2021 with no known "
        "loss of supply, so the two Hormuz dips look like gaps in AIS coverage, not lost barrels. Brent after them "
        "moved with the demand news of 2020 (the COVID collapse, the vaccine rally)"
        + (", and " + " and ".join(f"{PORTS[e['port']]} {e['t0']:%Y-%m}" for e in rally) +
           " beat 95% of placebo days at +20: the placebo cannot rule out demand news that happens to coincide"
           if rally else "") +
        ". A PortWatch dip is not a lost barrel: a scenario fed from live AIS has to tell a closure from a winter dip.")
    hit = [x for x in r["dated"] if x["port"] == HORMUZ and not x["rule"]]
    hz = ("day 0",) + tuple(f"+{h}" for h in HORIZONS)
    up = [(x, [k for k in range(len(hz)) if x["move"][k] > pq0[2, k]]) for x in hit]
    up = [(x, ks) for x, ks in up if ks]
    down = [f"{x['what']}: below the 5% from {hz[int(np.argmax(x['move'] < pq0[0]))]}" for x in hit if (x["move"] < pq0[0]).any()]
    out.append(
        f"- **Risk premium alone.** Of the {len(hit)} dated Hormuz-area attacks with no flow lost, "
        + ("; ".join(f"\"{x['what']}\" beat Brent's own 95% at " + " and ".join(hz[k] for k in ks) + " (" +
                     ", ".join(f"{100 * x['move'][k]:+.1f}%" for k in ks) + ")" for x, ks in up)
           if up else "none beat Brent's own 95%") +
        f"; the other {len(hit) - len(up)} stayed at or below it" +
        (f" ({'; '.join(down)}, with the COVID collapse)" if down else "") + ". ")
    big = max(hit, key=lambda x: x["move"][1])
    out[-1] += (f"The largest 5-day move, after \"{big['what']}\", was {100 * big['move'][1]:+.1f}% and "
                f"{100 * big['move'][2]:+.1f}% by +20 days, against {100 * cl['move'][k20]:+.1f}% at +20 for the 2026 "
                "closure: risk without lost flow buys a smaller premium that fades within weeks.")
    p20 = 100 * (pq[2, k20] - pq[1, k20])
    p120 = 100 * (pq[2, k120] - pq[1, k120])
    e20, e120 = 100 * cl["move"][k20] / cl["lost"], 100 * cl["move"][k120] / cl["lost"]
    out.append(
        f"- **Power.** Brent's own 90% range over 20 trading days is {100 * pq[0, k20]:+.0f}% to {100 * pq[2, k20]:+.0f}% "
        f"(2019–2025). At the 2026 response ({e20:.2f}% per point at +20) a loss below {p20 / e20:.0f} Hormuz points cannot "
        f"be told from noise; at +120 ({e120:.2f}% per point) not even the 2026 closure can ({p120 / e120:.0f} points "
        "would be needed). No event since 2019 other than the closure is big enough to test the elasticity's size; "
        "the out-of-sample events test its sign and the role of rerouting.")
    out.append(
        f"- **The 2026 closure after +120 days.** Brent data now runs {cl['obs']} trading days past day 0. Brent per "
        f"point of strait flow lost was lowest in trading days {lo_b['a']}–{lo_b['b']} ({min(pts):.2f}%), when the "
        f"bypass ports made up {lo_b['offset']:.0%} of the Gulf's lost exports, and highest in days {hi_b['a']}–"
        f"{hi_b['b']} ({max(pts):.2f}%), when they made up "
        + (f"none: their own exports had fallen below the pre-closure level ({hi_b['offset']:.0%} of the Gulf's loss)"
           if hi_b["offset"] < 0 else f"{hi_b['offset']:.0%}") +
        f". The chain's flat level after +120 days ({100 * OP_E_LATE:.2f}% per point) is below what followed.")
    out.append(
        f"- **Proposed curve** (`notes/flow-premium.csv`, log premium per point of lost Hormuz flow): a jump of "
        f"{100 * fit['jump']:.2f}% per point on day 1, rising to {100 * fit['peak']:.2f}% on day {fit['d_peak']}, decaying "
        f"with a {fit['half_life']:.0f}-day half-life to a plateau of {100 * fit['plateau']:.2f}%, fitted to all "
        f"{cl['obs']} observed days; 90% band from the placebo (one event's noise). Beyond day {cl['obs']} it is an "
        "assumption: flat at the plateau, the band still widening.")
    out.append("")

    # The rule.
    q = r["flows"][HORMUZ][0].resample("QS").mean()
    out += [
        "## The rule, fixed before looking at Brent",
        "",
        "Set after looking at the PortWatch flow series and before computing any Brent change around an event:",
        "",
        f"- flow: the {SMOOTH}-day mean of daily tanker capacity as a share of the chokepoint's 2019–2024 average",
        f"- an event starts on the first day the {SMOOTH}-day share is at least {DROP * 100:.0f} points below its "
        f"pre-level (mean over days −{PRE[0]}..−{PRE[1]}) and stays there for {SUSTAIN} days running "
        f"(`flow_price.SUSTAIN`); one event per chokepoint per {GAP.days} days",
        f"- searched {WINDOW[0]} to {WINDOW[1]} at Hormuz and Bab el-Mandeb; an event is out of sample if its +120-day "
        f"window ends before {CLOSURE:%Y-%m-%d}",
        f"- news-matched: a dated disruption at that chokepoint between {-NEWS_MATCH[0]} days before and "
        f"{NEWS_MATCH[1]} days after day 0",
        f"- lost flow at +h: the pre-level minus the mean share from day 0 to +h; Brent: log change from {BASE_LAG} trading "
        "days before day 0",
        f"- placebo: the same Brent change from all {len(noise)} other trading days of {WINDOW[0][:4]}–2025 more than "
        f"{EXCLUDE} trading days from an event or a dated disruption, windows ending before {CLOSURE:%Y-%m-%d}; the band "
        f"is its {Q[0]:.0%}–{Q[1]:.0%} range divided by the event's lost flow",
        "",
        "Hormuz share by quarter (PortWatch): " + ", ".join(f"{t:%Y}Q{(t.month - 1) // 3 + 1} {v:.0%}"
                                                             for t, v in q.loc["2019":"2025"].items() if t.month in (1, 10)) +
        " (Q1 and Q4 only; the other quarters sit near or above 100%).",
        "",
        "| Chokepoint | Day 0 | Pre-level | Dated disruption within the match window | Status |",
        "|---|---|---|---|---|",
    ]
    for e in r["events"]:
        status = ("out of sample" if e["clean"] else "window overlaps the 2026 closure: left out")
        out.append(f"| {PORTS[e['port']]} | {e['t0']:%Y-%m-%d} | {e['pre']:.0%} | {e['news'] or 'none'} | {status} |")
    out.append("")

    # Per event.
    out += ["## Brent per point of lost flow, by event", "",
            "Lost, rerouted and net in points of that chokepoint's normal flow. Hormuz-equivalent: per point of Hormuz "
            f"tonnage (one Bab el-Mandeb point = {ratio[BABEL]:.3f} Hormuz points, from the two 2019–2024 means: "
            f"{r['flows'][BABEL][1] / 1e6:.3f} and {r['flows'][HORMUZ][1] / 1e6:.3f} million deadweight tonnes a day). "
            "p: share of placebo days with a Brent move at least as large.", ""]
    for e in cleans:
        conv = ratio[e["port"]]
        out += [f"### {PORTS[e['port']]}, day 0 {e['t0']:%Y-%m-%d} ({'news: ' + e['news'] if e['news'] else 'no dated disruption'})",
                "",
                "| Trading days | Date | Lost | Rerouted (Cape) | Net | Brent | % per point lost | Placebo 90% | p | "
                "% per Hormuz-eq. point, gross | % per Hormuz-eq. point, net |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, hh in enumerate(HORIZONS):
            lo, hi = placebo_band(noise[:, k], e["lost"][k])
            p = (noise[:, k] >= e["move"][k]).mean()
            out.append(
                f"| +{hh} | {brent.index[e['i0'] + hh]:%Y-%m-%d} | {e['lost'][k]:.0f} | "
                + (f"{e['rerouted'][k]:.0f} | {e['net'][k]:.0f}" if e["port"] == BABEL else "– | –") +
                f" | {100 * e['move'][k]:+.1f}% | "
                f"{f(per_point(e['move'][k], e['lost'][k]))} | {f(lo)} to {f(hi)} | {p:.2f} | "
                f"{f(per_point(e['move'][k], e['lost'][k] * conv))} | {f(per_point(e['move'][k], e['net'][k] * conv))} |")
        out.append("")
    out += ["### For comparison: the 2026 Hormuz closure (in sample: the chain is calibrated on it)", "",
            f"Day 0 {cl['start']:%Y-%m-%d} (flow_price's rule: 7-day share below 50% for {SUSTAIN} days). flow_price "
            f"scales by the trough: {cl['lost']:.0f} points lost (pre-level {cl['pre']:.0%}). The mean shortfall, as for the "
            "events above, is in the Lost column.", "",
            "| Trading days | Date | Lost (mean shortfall) | Brent | % per point (trough, the chain's) | "
            "% per point (mean shortfall) | Placebo 90% (trough) | p |",
            "|---|---|---|---|---|---|---|---|"]
    for k, hh in enumerate(HORIZONS):
        lo, hi = placebo_band(noise[:, k], cl["lost"])
        out.append(f"| +{hh} | {brent.index[cl['i0'] + hh]:%Y-%m-%d} | {cl['lost_h'][k]:.0f} | {100 * cl['move'][k]:+.1f}% | "
                   f"{per_point(cl['move'][k], cl['lost']):+.2f} | {per_point(cl['move'][k], cl['lost_h'][k]):+.2f} | "
                   f"{f(lo)} to {f(hi)} | {(noise[:, k] >= cl['move'][k]).mean():.2f} |")
    out.append("")

    # Out-of-sample test of the 2026 curve.
    out += ["## Does the 2026 response predict the other events?", "",
            "The 2026 closure's per-point response at each horizon (trough scaling, the chain's) times the event's lost "
            "flow in Hormuz-equivalent points, against Brent's actual move. Inside: the actual move lies within the "
            "prediction plus the placebo's centred 90% range (the event's own noise; the 2026 estimate's error is left "
            "out, so this is the strict version).", "",
            "| Event | Trading days | Lost, Hormuz-eq. points (gross / net) | Predicted, gross | Predicted, net | "
            "Actual | Noise, centred 90% | Inside (gross / net) |",
            "|---|---|---|---|---|---|---|---|"]
    for e in real:
        conv = ratio[e["port"]]
        for k, hh in enumerate(HORIZONS):
            e26 = cl["move"][k] / cl["lost"]
            pg, pn = e26 * e["lost"][k] * conv, e26 * e["net"][k] * conv
            lo, hi = pq[0, k] - pq[1, k], pq[2, k] - pq[1, k]
            ins = lambda pred: "yes" if pred + lo <= e["move"][k] <= pred + hi else "no"  # noqa: E731
            out.append(f"| {PORTS[e['port']]} {e['t0']:%Y-%m} | +{hh} | {e['lost'][k] * conv:.0f} / {e['net'][k] * conv:.0f} | "
                       f"{100 * pg:+.1f}% | {100 * pn:+.1f}% | {100 * e['move'][k]:+.1f}% | {100 * lo:+.0f}% to {100 * hi:+.0f}% | "
                       f"{ins(pg)} / {ins(pn)} |")
    out.append("")

    # Dated disruptions.
    out += ["## Dated disruptions: Brent with little or no flow lost", "",
            "Day 0 is the first trading day on or after the date. Lost: points of that chokepoint's normal flow over the "
            "first 20 trading days (negative: more flow than the month before). Placebo: Brent's own 90% range, unscaled.",
            "",
            "| Date | Chokepoint | What | Lost by +20 | Brent day 0 | +5 | +20 | +60 | +120 | Rule event? |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for x in r["dated"]:
        cells = []
        for k in range(len(HORIZONS) + 1):
            out_band = not (pq0[0, k] <= x["move"][k] <= pq0[2, k])
            cells.append(f"{100 * x['move'][k]:+.1f}%" + (" (outside)" if out_band else ""))
        out.append(f"| {x['date']} | {PORTS[x['port']]} | {x['what']} | {x['lost20']:+.0f} | " + " | ".join(cells) +
                   f" | {'yes' if x['rule'] else 'no'} |")
    out.append("| | | Placebo 90% (all trading days, 2019–2025) | | " +
               " | ".join(f"{100 * pq0[0, k]:+.0f}% to {100 * pq0[2, k]:+.0f}%" for k in range(len(HORIZONS) + 1)) + " | |")
    out.append("")

    # Rerouting and the bypass.
    out += ["## Rerouted, bypassed and lost barrels", "",
            "A tanker that goes round the Cape instead of through the Red Sea still delivers its cargo, two to three "
            "weeks later; only the barrels that do not show up anywhere are lost to the market. At Bab el-Mandeb the "
            "Cape's gain gives the rerouted part. Hormuz has no sea route around it: the only way round is by pipeline, "
            "the Saudi East–West line to Yanbu on the Red Sea and the UAE's Habshan–Fujairah line to the Gulf of Oman. "
            "PortWatch's tanker exports at those two ports, against exports from seven ports inside the Gulf "
            "(macro_data's `pipeline` block), show how much of the Gulf's lost exports the pipelines made up in 2026.", "",
            f"| Trading days after {cl['start']:%Y-%m-%d} | Dates | Hormuz share | Gulf ports' exports lost | Made up by the bypass "
            "ports | Net Hormuz points lost | Brent (mean) | % per point (gross) | % per net point |",
            "|---|---|---|---|---|---|---|---|---|"]
    for b in cl["blocks"]:
        net = b["gross"] * (1 - b["offset"])
        out.append(f"| {b['a']}–{b['b']} | {b['ta']:%Y-%m-%d} to {b['tb']:%Y-%m-%d} | {b['share']:.0%} | {b['gulf_lost']:.0%} | "
                   f"{b['offset']:.0%} | {net:.0f} of {b['gross']:.0f} | {100 * b['move']:+.1f}% | "
                   f"{per_point(b['move'], b['gross']):+.2f} | {per_point(b['move'], net):+.2f} |")
    out += ["",
            f"Over all {cl['obs']} days the bypass ports made up {cl['offset_all']:.0%} of the Gulf ports' lost exports. "
            "What this means for the Hormuz elasticity:", "",
            "- The chain's `lost` is points of tanker flow through the strait, and its elasticity has the 2026 bypass "
            "built in. A point of strait flow lost while the pipelines run full is a smaller net loss than a point lost "
            "while they are down; the 2026 path shows both, and Brent per gross point was lowest while the bypass "
            "carried the most and highest once it had failed. Per net point the swing is smaller but does not vanish "
            f"(the strait also partly reopened in the low block: its 7-day share reached {lo_b['peak_share']:.0%}).",
            "- Bab el-Mandeb's barrels were mostly rerouted, and its Brent response per Hormuz-equivalent point was below "
            "the 2026 closure's at +20 days (and close to it at +120 days), inside noise either way. That fits a market "
            "that prices lost barrels, not rerouted ones, but one event this small cannot show it.",
            "- So for a Hormuz scenario the elasticity should be read per point of strait flow with the pipelines "
            "responding as in 2026. A scenario with the pipelines out of action (as from late July 2026) belongs in "
            "the upper half of the band; one where the pipelines carry their full capacity from the first day belongs in "
            "the lower half.", ""]

    # The curve.
    obs = cl["obs"]
    cp = chain_premium()
    sel = [1, 5, 10, 20, 40, 60, 90, 120, obs, 200, CURVE_DAYS]
    inside = ((cl["path"] >= curve["e_low"].values[:obs]) & (cl["path"] <= curve["e_high"].values[:obs])).mean()
    out += ["## The proposed premium curve (`notes/flow-premium.csv`)", "",
            "Columns: trading_day (1 = the first trading day of the loss), e_low, e_mid, e_high (natural-log premium on "
            "Brent per point of lost Hormuz flow, so a scenario's premium is `lost` × e), source, generated. In % per "
            "point (100 × e):", "",
            "| Trading day | e_low | e_mid | e_high | 2026 closure, observed | Chain now (`oil_paths.premium`) |",
            "|---|---|---|---|---|---|"]
    for d in sel:
        row = curve.iloc[d - 1]
        o = f"{100 * cl['path'][d - 1]:.2f}" if d <= obs else "not observed"
        out.append(f"| {d} | {100 * row['e_low']:.2f} | {100 * row['e_mid']:.2f} | {100 * row['e_high']:.2f} | {o} | "
                   f"{100 * cp[d - 1]:.2f} |")
    out += ["",
            "How it is built, and what it assumes:", "",
            f"- **Mid, days 1–{obs}:** a least-squares fit to the 2026 closure's daily path (Brent's log change from 5 days "
            f"before day 0, divided by the {cl['lost']:.0f} points lost, the chain's `LOST_2026`): a jump on day 1, a linear "
            "rise to the peak, an exponential decay to a plateau. Fitted: jump "
            f"{100 * fit['jump']:.2f}%, peak {100 * fit['peak']:.2f}% on day {fit['d_peak']}, half-life "
            f"{fit['half_life']:.0f} days, plateau {100 * fit['plateau']:.2f}% per point; the daily path strays from it by "
            f"{100 * fit['rmse']:.2f}% per point (RMS); its largest swings are the dip around day 80 and the rise after "
            f"day 120. The jump is there because Brent was already {100 * cl['day0']:+.0f}% on day 0 and "
            f"{100 * cl['path'][0] * cl['lost']:+.0f}% on day 1: the 7-day flow share was {cl['share_m5']:.0%} five "
            f"trading days before day 0 and {cl['share_0']:.0%} on it, so the closure began before the rule's day 0.",
            f"- **Band, days 1–{obs}:** the mid plus the placebo's centred 5% and 95% Brent moves at that horizon "
            f"(2019–2025, {len(r['long_noise'])} days), divided by the {cl['lost']:.0f} points. That is the error of an "
            "elasticity read off one event: Brent would have moved that much without the closure. The low edge is floored "
            "at zero (no disruption here lowered Brent beyond noise). The band is wide because one event is all there is: "
            f"from about day {int(np.argmax(curve['e_low'].values == 0)) + 1} on the low edge is zero. {inside:.0%} of the 2026 "
            "path's observed days lie inside it (in sample).",
            f"- **Beyond day {obs} (assumption, no data):** the mid stays at its day-{obs} value, "
            f"{100 * curve['e_mid'].iloc[obs - 1]:.2f}% per point (the plateau), which supposes a loss that lasts "
            "keeps its premium: no further fading from demand cuts, stock releases or new supply, and no further rise from "
            "running stocks down. The 2026 path between days 60 and the last observed day did not fade (it rose as the "
            "bypass failed), which is the reason for not decaying it. The band keeps widening with the placebo's longer "
            "horizons, up to 12 months.",
            "- **The out-of-sample events do not move it.** Bab el-Mandeb's response is inside the noise of the 2026 "
            "response scaled to its size, and the other dips are not supply losses, so there is nothing to pool with "
            "the 2026 closure; they are consistent with its sign and with rerouted barrels counting for less.",
            f"- **Against the chain now:** the chain's peak is {100 * OP_E_PEAK:.2f}% per point on day {OP_D_PEAK} (the "
            f"highest close within 90 days) and its level after day {OP_D_LATE} is {100 * OP_E_LATE:.2f}% (one day's close). "
            f"The fit's plateau, {100 * fit['plateau']:.2f}%, uses every observed day after the peak, including the rise "
            "after day 120.",
            "- **Use in the chain:** the band is the uncertainty of the mean premium, not of Brent's path; the GARCH "
            "paths add Brent's own noise on top. Draw one curve per path (for example e_mid plus a standard normal times "
            "the half-width on its side over 1.645, clipped at zero) so the two are not merged into one number.",
            "",
            "**Limits.** Every number past the 2026 closure itself comes from events too small to test the size of the "
            "elasticity: the out-of-sample evidence checks the sign and the rerouting argument, not the scale. The placebo "
            "is 2019–2025, which includes the COVID collapse and 2022; a calmer period would give a narrower band. "
            "PortWatch counts AIS-visible tankers: its Hormuz share dips in several winters with no known disruption, and it "
            "misses dark-fleet transits. Capacity is deadweight tonnes of tankers passing, laden or not, so the "
            "Hormuz-equivalent scaling and the Cape's rerouted share are rough. The bypass shares use seven Gulf ports and "
            "two bypass ports, not every terminal.",
            ""]
    return out


LLOYDS = ("Lloyd's List Intelligence, Strait of Hormuz Brief, 9 September 2026",
          "https://www.lloydslistintelligence.com/resources/blog/strait-of-hormuz-brief-9-september-2026")
LLOYDS_AUG_CRUDE = 112  # "at least 112 non-Iranian-linked crude tanker transits" in August (ships over 10,000 dwt)


def iea_report(r: dict, x: dict) -> list[str]:
    today = datetime.now(UTC).date().isoformat()
    brent, cl, noise, ratio = r["brent"], r["closure"], r["noise"], r["ratio"]
    figs, mon, iea, pwd, days = x["figs"], x["monthly"], x["iea"], x["pw_daily"], x["days"]
    obs, pre_iea, move = cl["obs"], mon["strait"].iloc[0], x["move"]
    share, n = r["flows"][HORMUZ][0], portwatch_daily(HORMUZ, "n_tanker")
    n_base = n.loc[md.SHARE_BASE[0]:md.SHARE_BASE[1]].mean()
    used = figs[(figs["used"] == "yes") & (figs["measure"] == "strait")].set_index("period")
    months = pd.period_range(mon.index[0], days[-1].to_period("M"), freq="M")
    dm = days.to_period("M")
    pq = np.quantile(noise, [Q[0], 0.5, Q[1]], axis=0)
    avg25 = figs.loc[(figs["period"] == "2025") & (figs["measure"] == "strait"), "mb_d"].iloc[0]
    link = lambda row: f"[{row['source'].split(' (')[0]}]({row['url']}), {row['published']}"  # noqa: E731
    yes = lambda v: "yes" if v else "no"  # noqa: E731
    each = lambda key, spec, qs: ", ".join(format(q[key], spec) for q in qs)  # noqa: E731

    rows = []
    for m in months:
        f_ = mon["strait"].get(m, np.nan)
        pw = share.loc[str(m)]
        rows.append({"m": m, "iea": f_, "byp": mon["bypass"].get(m, np.nan), "iea_lost": 100 * (1 - f_ / pre_iea),
                     "pw": pw.mean(), "pw_days": int(pw.notna().sum()), "pw_lost": 100 * (cl["pre"] - pw.mean()),
                     "n": n.loc[str(m)].mean(), "n_sum": n.loc[str(m)].sum(), "src": used.loc[str(m)] if str(m) in used.index else None})
    by = {str(q["m"]): q for q in rows}
    spring = [by[k] for k in ("2026-03", "2026-04", "2026-05")]
    summer = [q for q in rows if q["m"] >= pd.Period("2026-06", "M") and np.isfinite(q["iea"])]
    last_iea = rows[[i for i, q in enumerate(rows) if np.isfinite(q["iea"])][-1]]
    byp_summer = mon["bypass"].loc[pd.Period("2026-06", "M"):]
    after = days > days[41]  # past the first two months (42 trading days)
    e_pw, e_iea = r["curve"]["e_mid"].values, iea["curve"]["e_mid"].values
    rise = e_iea[:obs][after].mean() / e_pw[:obs][after].mean() - 1
    early = e_iea[:obs][~after].mean() / e_pw[:obs][~after].mean() - 1
    fit0, fit1, fitd, fitc, free = r["fit"], iea["fit"], pwd["fit"], x["iea_to_date"]["fit"], x["iea_free"]["fit"]
    pp = lambda l, sel: 100 * move[sel].mean() / l[sel].mean()  # noqa: E731  Brent per point over some days
    autumn = dm >= pd.Period("2026-09", "M")
    summer_d = (dm >= pd.Period("2026-06", "M")) & (dm <= pd.Period("2026-07", "M"))

    # Bab el-Mandeb, as report(): the 2026 response at each horizon times the event's Hormuz-equivalent loss.
    real = [e for e in r["events"] if e["clean"] and e["news"]]
    bab = []
    for e in real:
        conv = ratio[e["port"]]
        for k, hh in enumerate(HORIZONS):
            lo, hi = pq[0, k] - pq[1, k], pq[2, k] - pq[1, k]
            g, nt = e["lost"][k] * conv, e["net"][k] * conv
            pred = {key: (e26[k] * g, e26[k] * nt) for key, e26 in (("pw", cl["move"] / cl["lost"]), ("iea", iea["e26"]))}
            ins = {key: tuple(p + lo <= e["move"][k] <= p + hi for p in v) for key, v in pred.items()}
            bab.append({"e": e, "h": hh, "k": k, "g": g, "nt": nt, "pred": pred, "ins": ins, "lo": lo, "hi": hi})
    all_in = {key: all(all(b["ins"][key]) for b in bab) for key in ("pw", "iea")}

    # The 2026 premium in sample, by month: the curve times the lost flow it was fitted with, and the
    # mismatch of the IEA curve with the trough the chain's replay uses.
    replay = []
    for m in months[1:]:
        sel = dm == m
        if sel.any():
            replay.append({"m": m, "days": int(sel.sum()), "move": move[sel].mean(),
                           "pw": (cl["lost"] * e_pw[:obs])[sel].mean(), "iea": (iea["lost"] * e_iea[:obs])[sel].mean(),
                           "mix": (cl["lost"] * e_iea[:obs])[sel].mean(), "l_iea": iea["lost"][sel].mean(),
                           "l_pw": pwd["lost"][sel].mean()})

    out = [
        "# Hormuz lost flow in 2026: the IEA's barrels against PortWatch's AIS count, and the premium curve refitted",
        "",
        f"_Generated by `experiments/flow_events.py iea` on {today}. IEA: `notes/hormuz-iea-flows.csv`, every figure with "
        "its Oil Market Report or commentary, link and publication date (read 2026-10-25); the monthly values in the two "
        "commentaries are the data behind their charts (CC BY 4.0). The fit uses the rows marked `used`, the latest figure "
        "for each month. PortWatch: daily tanker capacity and tanker transits through the Strait of Hormuz (`chokepoint6`, "
        f"AIS-derived, fetched {fetched('portwatch_chokepoint6.json')}) to {share.dropna().index[-1]:%Y-%m-%d}, as "
        f"`flow_events.load_flow` computes it. Brent: FRED DCOILBRENTEU (fetched {fetched('fred_DCOILBRENTEU.csv')}) to "
        f"{brent.index[-1]:%Y-%m-%d}. Nothing here is synthetic. The IEA has no figure for {months[-1]:%B} yet: the fit "
        f"holds {last_iea['m']:%B}'s, an assumption. `notes/flow-premium.csv` is not changed: the refitted curve is in "
        "`notes/flow-premium-iea.csv`._",
        "",
        "## Summary",
        "",
        f"- **The IEA and PortWatch agree on the spring and part from June.** In March–May the IEA puts flows through the "
        f"strait at {each('iea', '.2f', spring)} mb/d against {pre_iea:.2f} in February: "
        f"{each('iea_lost', '.0f', spring)} points of pre-war flow lost, against PortWatch's "
        f"{each('pw_lost', '.0f', spring)} (its share {each('pw', '.1%', spring)} of the 2019–2024 normal, from a "
        f"pre-level of {cl['pre']:.0%}). From June the IEA has the strait carrying "
        f"{min(q['iea'] for q in summer):.1f}–{max(q['iea'] for q in summer):.1f} mb/d "
        f"({min(q['iea_lost'] for q in summer):.0f}–{max(q['iea_lost'] for q in summer):.0f} points lost) while PortWatch "
        f"shows about {(by['2026-06']['pw'] + by['2026-07']['pw']) / 2:.0%} of normal in June and July and under 1% from "
        f"August ({by['2026-08']['pw_lost']:.0f} points lost). In {last_iea['m']:%B} the IEA has the strait at "
        f"{last_iea['iea'] / pre_iea:.0%} of its February flow ({last_iea['iea']:.1f} mb/d); PortWatch has it at "
        f"{last_iea['pw']:.1%} of normal.",
        "- **The gap is barrels AIS cannot see.** The IEA counts oil that leaves the Gulf through the strait whether or not "
        "its transponder is on, including dark exits along the Omani coast and Gulf of Oman ship-to-ship transfers; "
        "PortWatch counts AIS-visible tankers crossing its strait polygon. Lloyd's List counted at least "
        f"{LLOYDS_AUG_CRUDE} non-Iranian-linked crude tanker transits in August; PortWatch logged {by['2026-08']['n_sum']:.0f} "
        "tanker transits of every kind, in both directions. PortWatch's pre-war level is low too: its February share, "
        f"{by['2026-02']['pw']:.0%}, is the winter dip it shows every year, while the IEA has February at "
        f"{pre_iea / avg25:.0%} of the 2025 average. So the IEA series is the better measure of barrels lost.",
        f"- **Refitted per point of the IEA's lost flow, day by day:** a jump of {100 * fit1['jump']:.2f}% per point on day 1, "
        f"rising to {100 * fit1['peak']:.2f}% on day {fit1['d_peak']}, decaying with a {fit1['half_life']:.0f}-day half-life "
        f"to a plateau of {100 * fit1['plateau']:.2f}% (now: {100 * fit0['jump']:.2f}%, {100 * fit0['peak']:.2f}% on day "
        f"{fit0['d_peak']}, {fit0['half_life']:.0f} days, {100 * fit0['plateau']:.2f}%). The first two months move little "
        f"({early:+.0%} on average over days 1–42: the IEA's loss is {each('iea_lost', '.0f', spring)} points, a little "
        f"more than the trough's {cl['lost']:.0f}). After them the curve is {rise:+.0%} higher on average over the observed "
        f"days, and the level a scenario keeps beyond the data is {100 * e_iea[obs - 1]:.2f}% per point against "
        f"{100 * e_pw[obs - 1]:.2f}%.",
        f"- **But per IEA point, 2026 does not follow one decaying curve.** Brent per point lost was "
        f"{pp(iea['lost'], dm == pd.Period('2026-04', 'M')):.2f}% in April, {pp(iea['lost'], summer_d):.2f}% in June–July "
        f"and {pp(iea['lost'], autumn):.2f}% in September–October, when the IEA has the strait recovering. That autumn "
        "rise is not a strait-flow effect: the East–West pipeline was bombed on 11 September, Houthi attacks cut the Red "
        "Sea bypass, and stocks were drawing at record rates. Left free to rise, the fit chases it and gives up April "
        f"(its day-{obs} level would be {100 * free['e_last']:.2f}%); the recommended fit keeps the decay the curve is "
        f"meant to have. Either way it fits Brent's daily move a little worse in sample than the trough "
        f"(RMS {100 * fit1['rms_move']:.1f}% against {100 * fit0['rms_move']:.1f}%), and neither gets September–October.",
        f"- **Bab el-Mandeb still checks out:** the 2026 response per point of the IEA's loss, scaled to the 2023–24 "
        f"disruption, predicts its Brent move within noise at {'every' if all_in['iea'] else 'not every'} horizon from 5 to "
        f"120 trading days, as the trough-scaled response {'does' if all_in['pw'] else 'does not'}. The check is weak: "
        "Brent's own noise is wider than either prediction, so it cannot choose between them.",
        f"- **Recommendation: switch to the IEA's lost flow, as one change** (curve, replay path, app preset together; "
        f"details at the end). A sustained {cl['lost']:.0f}-point loss then carries {100 * cl['lost'] * e_iea[-1]:.0f}% "
        f"of log premium after 12 months, not {100 * cl['lost'] * e_pw[-1]:.0f}%. `notes/flow-premium.csv` stays as it "
        "is until that change lands.",
        "",
        "## What the IEA figures count",
        "",
        "- **Strait flow** is Gulf producers' oil exports shipped through the strait: crude, natural gas liquids and refined "
        "products (the April report's \"loadings of crude, natural gas liquids and refined products\"), Iran included. "
        "Pre-war, about 20 mb/d (15 crude, 5 products in 2025).",
        "- **Ship-to-ship transfers and dark transits are inside it.** The 22 June commentary's chart has a separate \"Gulf "
        "of Oman STS\" column (\"ship-to-ship transfers including dark activity exit of Hormuz via the Omani coastline\"), "
        "and its text's 2.7 mb/d for March–May is the strait column plus that one (2.72), not the strait column alone "
        "(2.35). The 18 September commentary's chart has no STS column and its strait values for March–May are those sums "
        "revised up a little (2.27, 3.33, 3.00); the October report says outright that STS transfers lifted \"total oil "
        "flows through the Strait\". Our reading: from 18 September on, the IEA's strait flow includes them.",
        "- **The bypass is separate:** Saudi Red Sea ports (the East–West pipeline to Yanbu), the UAE's Habshan–Fujairah "
        "pipeline, Iraq via Türkiye and Syria, and Iran's Jask terminal.",
        "- **\"Total flows\" in the June report is strait plus bypass:** its May low of 9.6 mb/d is the 22 June chart's three "
        "columns summed (9.63), and the July report's June total (16.1 mb/d, \"including volumes bypassing the Strait\") is "
        "6.5 above it. It is not a strait figure.",
        "- **Revisions.** August's strait flow was 7.58 mb/d (preliminary) on 18 September and 7.2 in the October report "
        "(September's 10.9 less its 3.7 rise); March–May rose by 0.03–0.23 mb/d between the June and September charts. "
        "The fit uses the latest figure for each month.",
        "",
        "## Month by month: the IEA against PortWatch",
        "",
        f"Lost: points of pre-war flow. IEA: 100 × (1 − month / February); PortWatch: its pre-level ({cl['pre']:.0%}, the "
        f"mean 7-day share over days −29..−7 before {cl['start']:%Y-%m-%d}) minus the month's mean daily share, as "
        "`flow_events` measures the 2026 loss. PortWatch tankers: transits a day, all tanker types, both directions "
        f"(2019–2024 mean {n_base:.0f}).",
        "",
        "| Month | IEA strait, mb/d | IEA bypass, mb/d | IEA strait, % of February | Lost, IEA | PortWatch share of "
        "normal | Lost, PortWatch | PortWatch tankers a day | IEA source |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for q in rows:
        has = np.isfinite(q["iea"])
        days_note = f" ({q['pw_days']} days)" if q["pw_days"] < q["m"].days_in_month else ""
        out.append(f"| {q['m']:%Y-%m} | {f(q['iea'], '.2f') if has else 'none yet'} | "
                   f"{f(q['byp'], '.2f') if np.isfinite(q['byp']) else 'none yet'} | "
                   f"{f(100 * q['iea'] / pre_iea, '.0f') + '%' if has else '–'} | {f(q['iea_lost'], '.0f') if has else '–'} | "
                   f"{q['pw']:.1%}{days_note} | {q['pw_lost']:.0f} | {q['n']:.1f} | {link(q['src']) if q['src'] is not None else '–'} |")
    out += ["",
            f"In the fit, {months[-1]:%B} (trading days {int(np.argmax(x['held'])) + 1}–{obs}) holds {last_iea['m']:%B}'s "
            f"{last_iea['iea_lost']:.0f} points: an assumption, no IEA figure yet.",
            "",
            "## Why they differ",
            "",
            "- **Dark transits.** \"Since April, the UAE has also been ramping up exports through the Strait of Hormuz along "
            "the Omani coastline with tankers' transponders turned off to avoid detection\" (IEA commentary, 22 June). A "
            "tanker with AIS off is not in PortWatch's count. Lloyd's List, which adds transits it identifies as dark, "
            f"counted at least {LLOYDS_AUG_CRUDE} non-Iranian-linked crude tanker transits in August "
            f"([{LLOYDS[0]}]({LLOYDS[1]})), and expects the figure to rise as more dark transits are found; PortWatch "
            f"has {by['2026-08']['n_sum']:.0f} tanker transits of all types for the month.",
            "- **Ship-to-ship transfers in the Gulf of Oman.** Oil shuttled out along the Omani coast and transferred to larger "
            "ships outside the strait is strait flow for the IEA; the shuttles are small, often dark, and the large ships "
            "never cross PortWatch's polygon. The IEA's STS column rose from 0.30 mb/d in April to 1.78 in the first half "
            "of June, and the October report credits \"robust\" STS for September's rise to 10.9 mb/d.",
            "- **AIS gaps and spoofing.** PortWatch's Hormuz share dips every winter with no supply lost (61–82% of normal in "
            "Q1 from 2019 to 2025, `notes/flow-events.md`), so its 2026 pre-level is low before the war starts. Jamming and "
            "spoofed positions in the Gulf hide or misplace ships further (Windward: 61% of logged August transits false "
            "because of spoofing, via `docs/ideas.md`; not checked at source).",
            "- **The barrels had to go somewhere.** Gulf production recovered to 23.9 mb/d in July (IEA, August report) and "
            "oil on water rose 103 mb in September \"amid a sharp rise in Gulf exports\" (October report). Gulf storage was "
            f"filling from March (March and April reports) and the bypass carried {byp_summer.min():.1f}–"
            f"{byp_summer.max():.1f} mb/d from June, so that output needed several mb/d through the strait; PortWatch's "
            "share under 1% (about 0.2 mb/d of a 20 mb/d normal) cannot carry it. Production and stocks are measured apart "
            "from tanker tracking, so this check does not lean on the IEA's strait estimate alone.",
            "- **What PortWatch measures is different anyway:** deadweight tonnes of tankers passing, laden or in ballast, both "
            "ways. In normal times that tracks barrels; in 2026, with dark laden exits and a changed fleet, it does not.",
            "",
            "## Every IEA figure used or checked",
            "",
            "From `notes/hormuz-iea-flows.csv` (the exact words of each are in its `statement` column).",
            "",
            "| Period | Measure | mb/d | What it counts | Source | Used in the fit |",
            "|---|---|---|---|---|---|"]
    for _, row in figs.iterrows():
        out.append(f"| {row['period']} | {row['measure']} | {row['mb_d']:g} | {row['counts']} | {link(row)} | {row['used']} |")
    out += ["",
            "## The premium curve per point of the IEA's lost flow (`notes/flow-premium-iea.csv`)",
            "",
            "Each observed trading day's Brent move (log change from 5 trading days before day 0, as now) is divided by that "
            "day's lost flow, and the same jump-ramp-decay-plateau curve is fitted with each day weighted by its lost flow "
            "squared, which fits the move itself (move ≈ lost × curve). With a constant loss that is the current fit. The "
            "band is the same placebo divided by each day's loss, held at the last day's beyond the data. The plateau may "
            "not exceed the peak (the shape is a decay; the trough's fit is the same with or without that rule). Three "
            f"other fits show what drives the change: PortWatch day by day (its 7-day share against the {cl['pre']:.0%} "
            "pre-level), the IEA's mean loss to date (a premium that follows cumulative barrels lost), and the IEA fit "
            "with the tail free to rise.",
            "",
            "| Lost flow | Lost, observed days | Jump | Peak | Peak day | Half-life | Plateau | Day-159 level | RMS error of "
            "Brent's move |",
            "|---|---|---|---|---|---|---|---|---|"]
    for name, l, p, last in (("PortWatch trough, held (`notes/flow-premium.csv`)", np.full(obs, cl["lost"]), fit0, e_pw[obs - 1]),
                             ("**IEA month by month (`notes/flow-premium-iea.csv`)**", iea["lost"], fit1, e_iea[obs - 1]),
                             ("PortWatch day by day", pwd["lost"], fitd, pwd["curve"]["e_mid"].iloc[obs - 1]),
                             ("IEA, mean loss to date", x["iea_to_date"]["lost"], fitc,
                              x["iea_to_date"]["curve"]["e_mid"].iloc[obs - 1]),
                             ("IEA, tail free to rise (not used)", iea["lost"], free, free["e_last"])):
        span = f"{l.min():.0f}" if l.min() == l.max() else f"{l.min():.0f}–{l.max():.0f}"
        out.append(f"| {name} | {span} | {100 * p['jump']:.2f}% | {100 * p['peak']:.2f}% | {p['d_peak']} | "
                   f"{p['half_life']:.0f} days | {100 * p['plateau']:.2f}% | {100 * last:.2f}% | {100 * p['rms_move']:.1f}% |")
    out += ["",
            f"PortWatch day by day fits Brent best, for the wrong reason: its loss is smallest in June–July, when Brent fell, "
            "and back at the trough from August, when Brent rose; but from August PortWatch's loss is AIS going dark, not "
            "barrels (the IEA has the strait carrying 7–11 mb/d). The fit in sample cannot choose the measure. The mean loss "
            "to date moves slowly, so its curve stays close to the trough's.",
            "",
            "In % per point (100 × e):",
            "",
            "| Trading day | Date | Lost, IEA | Observed, per IEA point | e_mid, IEA | e_low–e_high, IEA | Observed, per trough "
            "point | e_mid now |",
            "|---|---|---|---|---|---|---|---|"]
    ci = iea["curve"]
    for d in [1, 5, 10, 20, 42, 60, 90, 120, 140, obs, 200, CURVE_DAYS]:
        seen = d <= obs
        out.append(f"| {d} | {days[d - 1]:%Y-%m-%d} | {iea['lost'][d - 1]:.0f}{' (held)' if x['held'][d - 1] else ''} | "
                   f"{100 * iea['path'][d - 1]:.2f} | " if seen else f"| {d} | – | – | not observed | ")
        out[-1] += (f"{100 * ci['e_mid'].iloc[d - 1]:.2f} | {100 * ci['e_low'].iloc[d - 1]:.2f}–{100 * ci['e_high'].iloc[d - 1]:.2f} | "
                    f"{f(100 * cl['path'][d - 1]) if seen else 'not observed'} | {100 * e_pw[d - 1]:.2f} |")
    out += ["",
            "By month, Brent's mean move and what each lost-flow measure makes of it (% per point):",
            "",
            "| Month | Trading days | Brent, mean log move | Lost, trough | Lost, IEA | Lost, PortWatch day by day | Per "
            "trough point | Per IEA point |",
            "|---|---|---|---|---|---|---|---|"]
    for q in replay:
        out.append(f"| {q['m']:%Y-%m} | {q['days']} | {100 * q['move']:+.1f}% | {cl['lost']:.0f} | {q['l_iea']:.0f} | "
                   f"{q['l_pw']:.0f} | {100 * q['move'] / cl['lost']:.2f} | {100 * q['move'] / q['l_iea']:.2f} |")
    out += ["",
            "## Does the refitted curve still predict Bab el-Mandeb?",
            "",
            "As in `notes/flow-events.md`: the 2026 response at each horizon (Brent's move divided by the lost flow on that "
            "day) times the 2023–24 event's loss in Hormuz-equivalent points, gross and net of rerouting round the Cape; "
            "inside means the actual move lies within the prediction plus the placebo's centred 90% range.",
            "",
            "| Event | Trading days | Lost, Hormuz-eq. (gross / net) | Per point, trough | Per point, IEA (lost) | "
            "Predicted, trough (gross / net) | Predicted, IEA (gross / net) | Actual | Noise, centred 90% | Inside, trough "
            "/ IEA (gross; net) |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for b in bab:
        e, k = b["e"], b["k"]
        out.append(f"| {PORTS[e['port']]} {e['t0']:%Y-%m} | +{b['h']} | {b['g']:.0f} / {b['nt']:.0f} | "
                   f"{100 * cl['move'][k] / cl['lost']:.2f} | {100 * iea['e26'][k]:.2f} ({iea['lost_h'][k]:.0f}) | "
                   f"{100 * b['pred']['pw'][0]:+.1f}% / {100 * b['pred']['pw'][1]:+.1f}% | "
                   f"{100 * b['pred']['iea'][0]:+.1f}% / {100 * b['pred']['iea'][1]:+.1f}% | {100 * e['move'][k]:+.1f}% | "
                   f"{100 * b['lo']:+.0f}% to {100 * b['hi']:+.0f}% | {yes(b['ins']['pw'][0])} / {yes(b['ins']['iea'][0])}; "
                   f"{yes(b['ins']['pw'][1])} / {yes(b['ins']['iea'][1])} |")
    out += ["",
            "## What it does to the chain, and the recommendation",
            "",
            "The chain's premium is `lost` × e(day). Fitted with one lost-flow measure, a curve only reproduces 2026 when it "
            "is used with that measure. In sample, by month (log premium, %):",
            "",
            "| Month | Brent, actual | Trough × curve now (the chain's replay) | IEA path × IEA curve | Trough × IEA curve "
            "(a mismatch) |",
            "|---|---|---|---|---|"]
    for q in replay:
        out.append(f"| {q['m']:%Y-%m} | {100 * q['move']:+.1f}% | {100 * q['pw']:+.1f}% | {100 * q['iea']:+.1f}% | "
                   f"{100 * q['mix']:+.1f}% |")
    last = replay[-1]
    mean_l = iea["lost"].mean()
    worst = max((q for q in replay if q["m"] >= pd.Period("2026-06", "M")), key=lambda q: q["mix"] - q["move"])
    cover = (move[autumn] <= iea["lost"][autumn] * ci["e_high"].values[:obs][autumn]).mean()
    out += ["",
            f"For a scenario, the same {cl['lost']:.0f} points held for 12 months give a log premium of "
            f"{100 * cl['lost'] * e_pw[-1]:.0f}% on day {CURVE_DAYS} with the current curve and "
            f"{100 * cl['lost'] * e_iea[-1]:.0f}% with the IEA's (Brent × {np.exp(cl['lost'] * e_pw[-1]):.2f} against × "
            f"{np.exp(cl['lost'] * e_iea[-1]):.2f}). By the IEA's count, {cl['lost']:.0f} points held is a harsher closure "
            f"than 2026 was: its loss averaged {mean_l:.0f} points over the observed days and {last_iea['iea_lost']:.0f} in "
            f"{last_iea['m']:%B}, while Brent stood {100 * last['move']:+.0f}% (log) in {last['m']:%B}.",
            "",
            "**Recommendation: switch to the IEA's lost flow, as one change, and keep `notes/flow-premium.csv` until then.**",
            "",
            "- **Why switch.** The IEA's series is the better measure of barrels lost (above), and the chain's input is meant "
            "to be barrels: the app's slider is a share of normal flow, and the flow estimate that feeds the chain counts "
            "hidden ships, as the IEA does. Per point of those barrels the 2026 premium after the first two months was "
            f"higher than the current curve says ({rise:+.0%} over days 43–{obs}; plateau {100 * fit1['plateau']:.2f}% "
            f"against {100 * fit0['plateau']:.2f}%). Bab el-Mandeb does not object: it stays inside the noise at every "
            "horizon.",
            f"- **What it costs.** In sample the IEA curve fits Brent's daily move a little worse (RMS "
            f"{100 * fit1['rms_move']:.1f}% against {100 * fit0['rms_move']:.1f}%), and the 2026 replay's "
            f"{last['m']:%B} falls from {100 * last['pw']:+.0f}% to {100 * last['iea']:+.0f}% against "
            f"{100 * last['move']:+.0f}% actual. The trough misses less there only because it counts "
            f"{by[str(last['m'])]['pw_lost']:.0f} points lost where the IEA counts {last['l_iea']:.0f}; it does not explain "
            "the rise either. Keeping a denominator known to be wrong for a better fit in sample is not a reason to keep it.",
            "- **Why as one change.** A curve reproduces 2026 only with the lost flow it was fitted with. With the trough the "
            f"IEA curve overstates 2026 by up to {100 * (worst['mix'] - worst['move']):.0f} points of log premium "
            f"({worst['m']:%B}: {100 * worst['mix']:+.0f}% against {100 * worst['move']:+.0f}%), so the switch needs: "
            "`notes/flow-premium-iea.csv` as `notes/flow-premium.csv`; `oil_paths.premium` taking a lost-flow path by day, "
            f"not one number; the 2026 replay (`macro_chain.py`, the \"lost {cl['lost']:.0f}\" scenario) and the reserves "
            "restatement (`experiments/reserves.py` on `seb/reserves`) using the IEA path "
            f"({iea['lost'].max():.0f} points in March to {iea['lost'].min():.0f} in September); the app's 2026 preset the "
            "same; and `docs/chain.md` step 1. Until that lands, the current curve with its trough is the consistent pair.",
            "- **What it does not fix.** Neither curve reproduces September–October: the late premium came with the bypass "
            "attacks and the stock draw, which a premium per point of strait flow does not model. The "
            f"IEA curve's upper edge (e_high × lost) covers {cover:.0%} of September–October's trading days; a stock-draw "
            "term would be the next step.",
            "",
            "## Limits",
            "",
            "- **One event still sets the size.** The IEA's barrels change the denominator, not the number of closures.",
            "- **The IEA's figures are estimates** built from tanker tracking and other data, and they are revised: August "
            "moved from 7.58 to 7.2 mb/d between September and October, and March–May rose by 0.03–0.23 mb/d between June "
            "and September. That STS transfers sit inside the 18 September strait column is our reading of the sums, "
            "not something the chart says.",
            "- **Monthly steps.** Each trading day takes its month's flow, so the loss changes on the first of the month; "
            "inside June the strait went from 6.3 mb/d (first half, with STS, 22 June chart) to 9.4 for the month.",
            f"- **{months[-1]:%B} has no IEA figure yet** and holds {last_iea['m']:%B}'s; the October report warns that renewed "
            "attacks threaten the recovery, so the loss may have grown again.",
            f"- **Points of February's flow** ({pre_iea:.2f} mb/d). Against the 2025 average ({avg25:g} mb/d) each point is "
            f"{pre_iea / avg25 - 1:.0%} smaller and the premium per point {pre_iea / avg25 - 1:.0%} larger.",
            "- **Strait flow only.** The bypass stays inside the curve as it ran in 2026; the IEA's total exports (strait plus "
            "bypass) would be a measure of barrels lost to the market as a whole, and are in the table for that.",
            "- **The Bab el-Mandeb conversion** into Hormuz points still uses PortWatch's tonnage at the two straits.",
            ""]
    return out


def write_curve(r: dict, curve: pd.DataFrame | None = None, path=CURVE, obs_src: str | None = None) -> None:
    c, cl = r["curve"] if curve is None else curve, r["closure"]
    today = datetime.now(UTC).date().isoformat()
    obs_src = obs_src or (f"fit to the 2026 Hormuz closure from {cl['start']:%Y-%m-%d} (FRED DCOILBRENTEU fetched "
                          f"{fetched('fred_DCOILBRENTEU.csv')}; IMF PortWatch fetched {fetched('portwatch_chokepoint6.json')}; "
                          f"{cl['lost']:.0f} points lost); band: 2019-2025 placebo / {cl['lost']:.0f}")
    ext_src = f"assumption beyond observed day {cl['obs']}: mid flat at the fitted plateau; band from the 2019-2025 placebo"
    out = pd.DataFrame({"trading_day": c["trading_day"], "e_low": c["e_low"].round(6), "e_mid": c["e_mid"].round(6),
                        "e_high": c["e_high"].round(6), "source": np.where(c["observed"], obs_src, ext_src),
                        "generated": today})
    out.to_csv(path, index=False)


def main_iea(out_dir) -> None:
    r = study()
    x = refit_iea(r)
    cl, iea = r["closure"], x["iea"]
    out_dir.mkdir(parents=True, exist_ok=True)
    src = (f"fit to the 2026 Hormuz closure from {cl['start']:%Y-%m-%d} per point of the IEA's lost strait flow day by day "
           f"({iea['lost'].min():.0f}-{iea['lost'].max():.0f} points of February's flow, notes/hormuz-iea-flows.csv; October "
           f"held at September's, an assumption; FRED DCOILBRENTEU fetched {fetched('fred_DCOILBRENTEU.csv')}); band: "
           "2019-2025 placebo / each day's lost flow")
    write_curve(r, iea["curve"], out_dir / IEA_CURVE, src)
    (out_dir / IEA_OUT).write_text("\n".join(iea_report(r, x)), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print((out_dir / IEA_OUT).read_text(encoding="utf-8"))


def main() -> None:
    if sys.argv[1:2] == ["iea"]:
        return main_iea(md.ROOT / (sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "notes"))
    r = study()
    write_curve(r)
    OUT.write_text("\n".join(report(r)), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    print(OUT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
