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

    uv run experiments/flow_events.py   # writes notes/flow-events.md and notes/flow-premium.csv
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

def load_flow(port: str) -> tuple[pd.Series, float]:
    """Daily tanker capacity through a chokepoint as a share of its 2019-2024 mean, and that mean
    (deadweight tonnes a day), from the PortWatch cache macro_data keeps."""
    md.fetch_portwatch(f"{port}:capacity_tanker")  # make sure the cache exists
    df = pd.DataFrame(json.loads((md.RAW / f"portwatch_{port}.json").read_text(encoding="utf-8")))
    dates = pd.to_datetime(df["date"], unit="ms") if pd.api.types.is_numeric_dtype(df["date"]) \
        else pd.to_datetime(df["date"])
    s = pd.Series(df["capacity_tanker"].astype(float).values, index=dates).sort_index().asfreq("D")
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


def fit_curve(y: np.ndarray) -> dict:
    """Least squares fit of curve_shape to a daily path y (days 1..len(y)): a grid over d_peak and
    the half-life, with jump, peak and plateau linear given those two."""
    d = np.arange(1, len(y) + 1, dtype=float)
    best = None
    for dp in D_PEAK_GRID:
        for hl in HALF_LIFE_GRID:
            w = np.exp(-np.log(2) / hl * np.clip(d - dp, 0, None))
            X = np.column_stack([np.where(d <= dp, 1 - d / dp, 0), np.where(d <= dp, d / dp, w),
                                 np.where(d <= dp, 0, 1 - w)])
            b, *_ = np.linalg.lstsq(X, y, rcond=None)
            sse = float(((y - X @ b) ** 2).sum())
            if best is None or sse < best["sse"]:
                best = {"jump": b[0], "peak": b[1], "d_peak": dp, "half_life": float(hl), "plateau": b[2], "sse": sse}
    best["rmse"] = np.sqrt(best["sse"] / len(y))
    return best


def premium_curve(y: np.ndarray, noise: np.ndarray, lost: float, days: int = CURVE_DAYS) -> pd.DataFrame:
    """e_low, e_mid, e_high per trading day 1..days (log premium per point of lost flow): e_mid is
    the fit to the observed path y, held at its value on the last observed day after that (an
    assumption); the band adds the placebo's centred 5% and 95% moves at each horizon divided by
    the event's lost flow (the error of a one-event estimate), with the low edge floored at zero.
    noise: [n, days]."""
    p = fit_curve(y)
    d = np.arange(1, days + 1, dtype=float)
    mid = curve_shape(d, p["jump"], p["peak"], p["d_peak"], p["half_life"], p["plateau"])
    mid[len(y):] = mid[len(y) - 1]
    q = np.quantile(noise, [Q[0], 0.5, Q[1]], axis=0)
    low = np.maximum(mid + (q[0] - q[1]) / lost, 0.0)
    high = mid + (q[2] - q[1]) / lost
    return pd.DataFrame({"trading_day": d.astype(int), "e_low": low, "e_mid": mid, "e_high": high,
                         "observed": d <= len(y)}), p


def chain_premium(days: int = CURVE_DAYS) -> np.ndarray:
    """oil_paths.premium(1, days) as of commit 1b66286: the chain's current curve per point."""
    d = np.arange(1, days + 1, dtype=float)
    k = np.log(OP_E_PEAK / OP_E_LATE) / (OP_D_LATE - OP_D_PEAK)
    return np.where(d <= OP_D_PEAK, OP_E_PEAK * d / OP_D_PEAK,
                    np.where(d <= OP_D_LATE, OP_E_PEAK * np.exp(-k * (d - OP_D_PEAK)), OP_E_LATE))


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


def write_curve(r: dict) -> None:
    c, fit, cl = r["curve"], r["fit"], r["closure"]
    today = datetime.now(UTC).date().isoformat()
    obs_src = (f"fit to the 2026 Hormuz closure from {cl['start']:%Y-%m-%d} (FRED DCOILBRENTEU fetched "
               f"{fetched('fred_DCOILBRENTEU.csv')}; IMF PortWatch fetched {fetched('portwatch_chokepoint6.json')}; "
               f"{cl['lost']:.0f} points lost); band: 2019-2025 placebo / {cl['lost']:.0f}")
    ext_src = f"assumption beyond observed day {cl['obs']}: mid flat at the fitted plateau; band from the 2019-2025 placebo"
    out = pd.DataFrame({"trading_day": c["trading_day"], "e_low": c["e_low"].round(6), "e_mid": c["e_mid"].round(6),
                        "e_high": c["e_high"].round(6), "source": np.where(c["observed"], obs_src, ext_src),
                        "generated": today})
    out.to_csv(CURVE, index=False)


def main() -> None:
    r = study()
    write_curve(r)
    OUT.write_text("\n".join(report(r)), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    print(OUT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
