# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "xlrd>=2.0", "openpyxl>=3.1"]
# ///
"""The first link of the chain: does oil flow through Hormuz (AIS) move the Brent price?

Flow is IMF PortWatch's daily tanker capacity through the Strait of Hormuz (deadweight tonnes, from
AIS), as a share of its 2019-2024 average; experiments/macro_data.py fetches and caches it.

1. Monthly regression, 2019 onwards: Brent's log change on the change in Hormuz flow share (lags
   0-2), with Bab el-Mandeb flow and the geopolitical-risk index as controls; with and without the
   2026 closure months. Newey-West errors.
2. Event study of the 2026 closure: the first day the 7-day average flow share stays below 50% for 14 days,
   and Brent's move from 5 trading days before to 5, 20 and 60 trading days after.

    uv run experiments/flow_price.py   # writes notes/flow-price-link.md
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import macro_data as md

OUT = md.ROOT / "notes" / "flow-price-link.md"
SUSTAIN = 14  # days the flow share must stay below 50% to count as the closure starting


def ols_hac(y, X, lag):
    inv = np.linalg.inv(X.T @ X)
    b = inv @ X.T @ y
    u = X * (y - X @ b)[:, None]
    S = u.T @ u
    for k in range(1, lag + 1):
        G = u[k:].T @ u[:-k]
        S += (1 - k / (lag + 1)) * (G + G.T)
    return b, np.sqrt(np.diag(inv @ S @ inv))


def daily_flow(port: str) -> pd.Series:
    md.fetch_portwatch(f"{port}:capacity_tanker")  # make sure the cache exists
    df = pd.DataFrame(json.loads((md.RAW / f"portwatch_{port}.json").read_text(encoding="utf-8")))
    dates = pd.to_datetime(df["date"], unit="ms") if pd.api.types.is_numeric_dtype(df["date"]) \
        else pd.to_datetime(df["date"])
    s = pd.Series(df["capacity_tanker"].astype(float).values, index=dates).sort_index()
    return s / s.loc[md.SHARE_BASE[0]:md.SHARE_BASE[1]].mean()


def main() -> None:
    brent_d = pd.read_csv(md.RAW / "fred_DCOILBRENTEU.csv", parse_dates=["observation_date"])
    brent_d = pd.Series(pd.to_numeric(brent_d["DCOILBRENTEU"], errors="coerce").values,
                        index=brent_d["observation_date"]).dropna()
    hormuz, babel = daily_flow("chokepoint6"), daily_flow("chokepoint4")
    gpr = md.fetch_gpr("GPR")

    # 1. Monthly regressions.
    m = pd.DataFrame({"brent": np.log(brent_d.resample("MS").mean()), "hormuz": hormuz.resample("MS").mean(),
                      "babel": babel.resample("MS").mean(), "gpr": gpr}).loc["2019-01-01":]
    d = pd.DataFrame({"y": m["brent"].diff() * 100, "const": 1.0})
    for k in range(3):
        d[f"hormuz_{k}"] = m["hormuz"].diff().shift(k) * 100  # pp change in flow share
    d["babel_0"] = m["babel"].diff() * 100
    d["gpr_0"] = m["gpr"].diff()
    d = d.dropna()
    rows = []
    for label, sample in (("2019 onwards, all months", d),
                          ("excluding the 2026 closure (Feb-Oct 2026)", d[(d.index < "2026-02-01") | (d.index > "2026-10-01")]),
                          ("2019-2025 only", d[d.index < "2026-01-01"])):
        cols = [c for c in d.columns if c != "y"]
        b, se = ols_hac(sample["y"].values, sample[cols].values, 6)
        idx = [cols.index(f"hormuz_{k}") for k in range(3)]
        total = b[idx].sum()
        X = sample[cols].values
        resid = sample["y"].values - X @ b
        r2 = 1 - resid.var() / sample["y"].var()
        rows.append(f"| {label} | {len(sample)} | {b[idx[0]]:+.3f} ± {se[idx[0]]:.3f} | {total:+.3f} | "
                    f"{b[cols.index('babel_0')]:+.3f} ± {se[cols.index('babel_0')]:.3f} | "
                    f"{b[cols.index('gpr_0')]:+.3f} ± {se[cols.index('gpr_0')]:.3f} | {r2:.2f} |")

    # 2. Event study of the closure.
    smooth = hormuz.rolling(7).mean()
    # The closure starts on the first day the 7-day flow share stays below 50% for 14 days in a row
    # (a one-off dip, like late December 2025, does not count).
    sustained = (smooth < 0.5).astype(int).rolling(SUSTAIN).min().shift(-(SUSTAIN - 1)) == 1
    start = sustained.loc["2025-06-01":][lambda s: s].index.min()
    trading = brent_d.index
    t0 = trading.searchsorted(start)
    base = brent_d.iloc[max(t0 - 5, 0)]
    event = [f"| {k:+d} | {trading[t0 + k]:%Y-%m-%d} | ${brent_d.iloc[t0 + k]:.2f} | "
             f"{100 * np.log(brent_d.iloc[t0 + k] / base):+.1f}% | {smooth.reindex([trading[t0 + k]], method='ffill').iloc[0]:.0%} |"
             for k in (-5, 0, 5, 20, 60, 120) if t0 + k < len(trading)]
    low = smooth.loc[start:start + pd.Timedelta(days=90)].min()
    peak = brent_d.loc[start:start + pd.Timedelta(days=90)]
    peak_move = 100 * np.log(peak.max() / base)
    flow_drop = 100 * (low - smooth.loc[:start].iloc[-30:-7].mean())

    today = datetime.now(UTC).date().isoformat()
    out = [
        "# Flow → Brent: the first link of the chain, from AIS",
        "",
        f"_Generated by `experiments/flow_price.py` on {today}. Flow: IMF PortWatch daily tanker capacity through "
        f"the Strait of Hormuz and Bab el-Mandeb (AIS-derived), {hormuz.index[0]:%Y-%m-%d} to {hormuz.index[-1]:%Y-%m-%d}, "
        f"as a share of the 2019–2024 average. Brent: FRED DCOILBRENTEU. Geopolitical risk: Caldara & Iacoviello GPR. "
        "Nothing here is synthetic._",
        "",
        "## Monthly regression",
        "",
        "Brent's monthly log change (%) on the change in Hormuz flow share (percentage points of normal, lags 0–2), "
        "with Bab el-Mandeb flow and geopolitical risk as controls. ± is a Newey–West standard error.",
        "",
        "| Sample | Months | Hormuz, same month | Hormuz, 3-month total | Bab el-Mandeb | Geopolitical risk | R² |",
        "|---|---|---|---|---|---|---|",
    ] + rows + [
        "",
        "A coefficient of −0.10 would mean: 10 points less flow through Hormuz (of normal) goes with Brent 1% higher.",
        "",
        f"## Event study: the 2026 closure (7-day flow share below 50% for 14 days running from {start:%Y-%m-%d})",
        "",
        "| Trading days from the closure | Date | Brent | Change since 5 days before | Hormuz flow share (7-day) |",
        "|---|---|---|---|---|",
    ] + event + [
        "",
        f"Within 90 days the 7-day flow share bottomed at {low:.0%} of normal ({flow_drop:+.0f} points from the month before), "
        f"and Brent peaked {peak_move:+.0f}% above its pre-closure level: about {peak_move / -flow_drop:.2f}% of Brent per "
        "point of lost flow at the peak.",
        "",
        "**Limits.** One closure dominates the sample, so the event study is one observation, and it mixes the lost "
        "barrels with a risk premium and with stock releases. The 2019–2025 months have small flow changes, so the "
        "regression without the closure says little either way. PortWatch counts AIS-visible tankers only: dark-fleet "
        "transits are missing, which is the gap the flow-estimate lane is meant to fill.",
        "",
    ]
    OUT.write_text("\n".join(out), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    print("\n".join(out))


if __name__ == "__main__":
    main()
