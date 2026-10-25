# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "xlrd>=2.0", "openpyxl>=3.1"]
# ///
"""Country trends for the app's Trends tab (notes/country-trends.json): prices over time by country,
and how well the industry run forecasts them.

For every country the sector run covers (experiments/sector_global.py, `--set sectors`), and every
country with consumer prices:

  consumer   annual inflation (% change on a year earlier), monthly: all items, food, motor fuels,
             electricity and gas. Eurostat HICP (prc_hicp_minr, ECOICOP 2) for Europe; BLS CPI on
             FRED for the US; ONS CPI (all items only) for the UK, which that HICP doesn't cover.
  price      each industry's producer price index (2021 = 100), monthly, as scored in the sector run
  output     each industry's output index (2021 = 100), monthly
  skill      forecast skill of those prices and output in the sector run: 1 - CRPS / climatology's,
             over all horizons (the report's skill), per industry and for the country as a whole
  resp       the extra % change in each industry's prices and output 1, 3, 6 and 12 months after a
             +10% Brent move, against no move (the report's "Response to +10% Brent")

Skill and responses are `global_lin`'s, the model whose responses the report and docs/macro-ensemble.md
quote. Both come from runs/macro/sector-fold-*.json (what-if mode: the network is given the oil path that
happened). Series data come from the caches in data/raw/macro/ that experiments/macro_data.py fills;
all-items HICP and four US CPI components are fetched here if missing.

    uv run experiments/country_trends.py      # writes notes/country-trends.json
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import macro_data as md

ROOT = Path(__file__).resolve().parent.parent
RUNS, OUT = ROOT / "runs" / "macro", ROOT / "notes" / "country-trends.json"
START = "2007-01"  # shown from here: takes in the 2008 oil spike
MODEL = "global_lin"
CONSUMER = [("TOTAL", "All items"), ("CP01", "Food and non-alcoholic drinks"), ("CP0722", "Motor fuels"),
            ("CP0451", "Electricity"), ("CP0452", "Gas")]
# BLS CPI on FRED (seasonally adjusted), the closest match to each HICP item
US_CONSUMER = {"TOTAL": "CPIAUCSL", "CP01": "CPIUFDSL", "CP0722": "CUSR0000SETB", "CP0451": "CUSR0000SEHF01",
               "CP0452": "CUSR0000SEHF02"}
HEADLINE = ("prc_hicp_minr", "unit=I15&freq=M&coicop18=TOTAL&sinceTimePeriod=1998-01")


def yoy(level: pd.Series) -> pd.Series:
    """% change on the same month a year earlier."""
    return 100 * (level / level.shift(12) - 1)


def rebase(level: pd.Series, year: str = "2021") -> pd.Series:
    """Index with the year's average = 100, as Eurostat's I21."""
    return 100 * level / level.loc[year].mean()


def pack(x: pd.Series, start: str = START, digits: int = 1) -> dict | None:
    """Monthly values from `start`, without leading and trailing gaps: {"from": "YYYY-MM", "v": [...]}."""
    x = x.loc[start:]
    ok = x.notna().to_numpy()
    if not ok.any():
        return None
    x = x.iloc[ok.argmax():len(ok) - ok[::-1].argmax()]
    return {"from": f"{x.index[0]:%Y-%m}", "v": [None if np.isnan(v) else round(float(v), digits) for v in x]}


def run_results(folds: list[dict], model: str = MODEL) -> dict:
    """Per sector-run series: forecast skill over all horizons, the per-output skill ratios, and the +10%
    Brent response by horizon (mean over the folds where it was scored), as in sector_global.report."""
    names = folds[0]["names"]
    stack = lambda get: np.vstack([np.array(get(f), float) for f in folds])  # noqa: E731
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        scale = np.nanmean(stack(lambda f: f["models"]["climatology"]["crps"]), 0)
        good = np.isfinite(scale) & (scale > 0)
        ratio = np.where(good, np.nanmean(stack(lambda f: f["models"][model]["crps"]), 0) / np.where(good, scale, 1), np.nan)
        seen = stack(lambda f: f["scored"]).astype(bool)
        resp = np.nanmean(np.where(seen, stack(lambda f: f["models"][model]["response_up10"]), np.nan), 0)
    out = {}
    for i, n in enumerate(names):
        key, h = n.split("@")
        d = out.setdefault(key, {"ratio": {}, "resp": {}})
        d["ratio"][int(h)], d["resp"][int(h)] = ratio[i], resp[i]
    for d in out.values():
        r = np.array([v for v in d["ratio"].values() if np.isfinite(v)])
        d["skill"] = 1 - r.mean() if len(r) else np.nan
    return out


def group_skill(results: dict, keys: list[str]) -> dict | None:
    """Skill over every output of these series (the report's by-country rows) and how many beat climatology."""
    r = np.array([v for k in keys for v in results[k]["ratio"].values() if np.isfinite(v)])
    per = [results[k]["skill"] for k in keys if np.isfinite(results[k]["skill"])]
    if not len(r):
        return None
    return {"skill": round(float(1 - r.mean()), 3), "beats": int(sum(s > 0 for s in per)), "of": len(per)}


def fetched(paths) -> str:
    days = sorted({datetime.fromtimestamp(p.stat().st_mtime, UTC).date().isoformat() for p in paths if p.exists()})
    return days[0] if len(days) == 1 else f"{days[0]} to {days[-1]}" if days else "not fetched"


def consumer_levels() -> tuple[dict, dict]:
    """{geo: {item: index}} for every HOUSEHOLD country and the US, and the sources."""
    path = md._get(md.EUROSTAT.format(*HEADLINE), md.RAW / "eurostat_headline_prc_hicp_minr.json")
    headline = md.jsonstat_frame(json.loads(path.read_text(encoding="utf-8")), "coicop18")
    levels = {}
    for geo in md.HOUSEHOLD_COUNTRIES:
        d = {}
        if (geo, "TOTAL") in headline:
            d["TOTAL"] = headline[(geo, "TOTAL")].where(lambda x: x > 0).dropna()
        for code, _ in CONSUMER[1:]:
            try:
                d[code] = md.fetch_eurostat_panel(f"consumer:{geo}:{code}")
            except ValueError:  # not published
                pass
        if d:
            levels[geo] = d
    levels["US"] = {code: md.fetch_fred(fred) for code, fred in US_CONSUMER.items()}
    # Eurostat's ECOICOP 2 HICP has no UK, so the UK gets ONS's all-items CPI (D7BT) and no item breakdown
    uk = {s.key: s for s in md.SERIES}["uk_cpi"]
    levels.setdefault("UK", {})["TOTAL"] = md.fetch_ons(uk.code)
    raw = [path, md.RAW / "eurostat_household_prc_hicp_minr.json"]
    src = {"eu": f"Eurostat HICP, prc_hicp_minr (ECOICOP 2; all items, food CP01, motor fuels CP0722, electricity "
                 f"CP0451, gas CP0452), fetched {fetched(raw)}",
           "US": "BLS CPI via FRED, seasonally adjusted (" + ", ".join(US_CONSUMER.values()) + "), fetched "
                 + fetched(md.RAW / f"fred_{c}.csv" for c in US_CONSUMER.values()),
           "UK": f"ONS CPI, all items (D7BT), fetched {fetched(md.RAW.glob('ons_d7bt*'))}; Eurostat's HICP has no UK, "
                 "so there is no item breakdown"}
    return levels, src


def main() -> None:
    folds = [json.loads(p.read_text()) for j in range(16) if (p := RUNS / f"sector-fold-{j}.json").exists()]
    if not folds:
        raise SystemExit("no runs/macro/sector-fold-*.json: run experiments/sector_global.py fold 0..7 first")
    results = run_results(folds)
    reg = {s.key: s for s in md.registry(md.SECTOR_BLOCKS)}
    keys = [k for k in results if k in reg and reg[k].target in ("price", "output") and np.isfinite(results[k]["skill"])]
    horizons = sorted(next(iter(results.values()))["resp"])
    levels, consumer_src = consumer_levels()

    countries = {}
    names = {"US": "United States"} | md.HOUSEHOLD_COUNTRIES
    for geo, d in levels.items():
        packed = {code: p for code, _ in CONSUMER if code in d and (p := pack(yoy(d[code])))}
        if packed:
            countries.setdefault(geo, {"name": names[geo]})["consumer"] = packed
    for k in keys:
        s, r = reg[k], results[k]
        x = md.fetch_eurostat_panel(s.code) if s.source == "eurostat_panel" else rebase(md.fetch_fred(s.code))
        c = countries.setdefault(s.geo, {"name": names[s.geo]})
        c.setdefault(s.target, {})[s.item] = (pack(x) or {}) | {
            "skill": round(float(r["skill"]), 3),
            "resp": [None if not np.isfinite(r["resp"][h]) else round(float(r["resp"][h]), 2) for h in horizons],
            "src": s.name.split(": ", 1)[1]}
    for geo, c in countries.items():
        c["skill"] = {t: g for t in ("price", "output")
                      if (g := group_skill(results, [k for k in keys if reg[k].geo == geo and reg[k].target == t]))}

    when = sorted(f["meta"]["generated"] for f in folds if "meta" in f)
    sector_raw = [md.RAW / "eurostat_sectors_sts_inppd_m.json", md.RAW / "eurostat_sectors_sts_inpr_m.json"]
    data = {
        "generated": datetime.now(UTC).date().isoformat(), "made_by": "experiments/country_trends.py", "start": START,
        "consumer_items": CONSUMER, "industries": [[c, n] for c, n, *_ in md.SECTORS], "horizons": horizons,
        "run": {"model": MODEL, "folds": len(folds), "first": folds[0]["test_dates"][0], "last": folds[-1]["test_dates"][-1],
                "origins": sum(len(f["test_dates"]) for f in folds), "fold_files": f"{when[0][:10]} to {when[-1][:10]}",
                "report": "notes/sector-global-results.md", "mode": "what-if: the network is given the oil path that happened"},
        "sources": {"consumer": consumer_src,
                    "industry": f"Eurostat sts_inppd_m (domestic producer prices) and sts_inpr_m (output, seasonally and "
                                f"calendar adjusted), 2021 = 100, fetched {fetched(sector_raw)}; US: BLS PPIs and Fed "
                                "industrial production via FRED, the closest NAICS industries, rebased to 2021 = 100"},
        "countries": dict(sorted(countries.items(), key=lambda kv: kv[1]["name"])),
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    n = {t: sum(len(c.get(t, {})) for c in countries.values()) for t in ("consumer", "price", "output")}
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.2f} MB): {len(countries)} countries, {n['consumer']} consumer, "
          f"{n['price']} price and {n['output']} output series")


if __name__ == "__main__":
    main()
