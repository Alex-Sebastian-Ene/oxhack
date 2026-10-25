# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1"]
# ///
"""Each map country's own oil numbers for the World view, so no country falls back to a typical profile.

1. Fuel pass-through: how far a country's pump prices follow Brent. For the countries with motor-fuel
   consumer prices in notes/country-trends.json (Eurostat HICP CP0722; US CPI motor fuel), the
   12-month log change in motor-fuel prices on the 12-month log change in Brent (FRED MCOILBRENTEU,
   US dollars), 2009-2025, Newey-West errors over 12 months. The slope is the share of a Brent move
   that reaches the pump. Countries without a series get the median slope, marked pooled.
2. Oil trade, UN Comtrade (public preview API, no key): each reporter's imports and exports of crude
   (HS 2709) and refined products (HS 2710), and its imports from the seven Gulf producers whose
   exports leave through the Strait of Hormuz. By value, in US dollars, for 2024, or 2023 where a
   country hasn't reported 2024 yet.
     gulf_share  imports from the Gulf producers / all oil imports. An upper bound for oil through the
                 strait: some Saudi oil leaves from Yanbu on the Red Sea and some UAE oil from Fujairah.
     m           net oil imports / oil imports: 1 for a country that re-exports nothing, below 0 for a
                 net exporter. Refining hubs (Singapore, Korea, the Netherlands) re-export products,
                 so m understates how much of their own use is imported.
   Countries that don't report to Comtrade (Taiwan among them) have no trade entry.

    uv run experiments/country_oil.py fuel    # pass-through (FRED + notes/country-trends.json)
    uv run experiments/country_oil.py trade   # Comtrade pulls, cached in data/raw/comtrade-oil/
    uv run experiments/country_oil.py         # both; writes notes/country-oil.json and notes/country-oil.md
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd

import macro_data as md
from hdi_link import ols_hac

TRENDS = md.ROOT / "notes" / "country-trends.json"
OUT_JSON = md.ROOT / "notes" / "country-oil.json"
OUT_MD = md.ROOT / "notes" / "country-oil.md"
RAW = md.ROOT / "data" / "raw" / "comtrade-oil"
SAMPLE = ("2009-01-01", "2025-12-01")
HAC_LAGS = 12
# country-trends geo code -> ISO3 as on the map (Natural Earth; Kosovo is KOS there)
GEO_ISO3 = {"AL": "ALB", "AT": "AUT", "BE": "BEL", "BA": "BIH", "BG": "BGR", "HR": "HRV", "CY": "CYP", "CZ": "CZE",
            "DK": "DNK", "EE": "EST", "FI": "FIN", "FR": "FRA", "GE": "GEO", "DE": "DEU", "EL": "GRC", "HU": "HUN",
            "IS": "ISL", "IE": "IRL", "IT": "ITA", "XK": "KOS", "LV": "LVA", "LT": "LTU", "LU": "LUX", "MT": "MLT",
            "ME": "MNE", "NL": "NLD", "MK": "MKD", "NO": "NOR", "PL": "POL", "PT": "PRT", "RO": "ROU", "RS": "SRB",
            "SK": "SVK", "SI": "SVN", "ES": "ESP", "SE": "SWE", "CH": "CHE", "TR": "TUR", "UK": "GBR", "US": "USA"}
CT = ("https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=&period={year}&partnerCode={partners}"
      "&cmdCode={cmd}&flowCode={flow}")
CT_REPORTERS = "https://comtradeapi.un.org/files/v1/app/reference/Reporters.json"
CMDS = (2709, 2710)  # crude, refined products
# the Gulf producers whose oil exports pass the strait (Oman's terminals are outside it), Comtrade codes
GULF = {682: "Saudi Arabia", 368: "Iraq", 784: "United Arab Emirates", 414: "Kuwait", 634: "Qatar", 48: "Bahrain", 364: "Iran"}
# the preview API returns at most 500 rows, so one product and a few partners per call
GULF_CALLS = [(682, 784), (368, 414), (634, 48, 364)]
YEARS = (2024, 2023)
PREVIEW_CAP = 500
PAUSE = 2.0  # seconds between calls to the public preview


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


# ------------------------------------------------------------------------------------------- pass-through
def yoy_series(packed: dict) -> pd.Series:
    """A notes/country-trends.json series ({from, v}: annual % changes, monthly) as a monthly Series."""
    idx = pd.date_range(packed["from"] + "-01", periods=len(packed["v"]), freq="MS")
    return pd.Series([np.nan if v is None else float(v) for v in packed["v"]], index=idx)


def passthrough(fuel_yoy: pd.Series, brent: pd.Series, sample=SAMPLE, lags=HAC_LAGS) -> dict | None:
    """Slope of the 12-month log change in fuel prices on the 12-month log change in Brent, with a
    Newey-West standard error and a 90% range. None with fewer than five years of overlap."""
    y = 100 * np.log1p(fuel_yoy / 100)
    x = 100 * np.log(brent).diff(12)
    d = pd.DataFrame({"y": y, "x": x}).loc[sample[0]:sample[1]].dropna()
    if len(d) < 60:
        return None
    X = np.column_stack([np.ones(len(d)), d["x"].to_numpy()])
    b, se = ols_hac(d["y"].to_numpy(), X, lags)
    resid = d["y"].to_numpy() - X @ b
    r2 = 1 - resid.var() / d["y"].var(ddof=0)
    e, s = float(b[1]), float(se[1])
    return {"e": round(e, 3), "se": round(s, 3), "lo": round(e - 1.645 * s, 3), "hi": round(e + 1.645 * s, 3),
            "r2": round(float(r2), 2), "n": int(len(d)), "from": d.index[0].strftime("%Y-%m"), "to": d.index[-1].strftime("%Y-%m")}


def fuel_section() -> dict:
    trends = json.loads(TRENDS.read_text(encoding="utf-8"))
    brent = md.fetch_fred("MCOILBRENTEU")
    fetched = datetime.fromtimestamp((md.RAW / "fred_MCOILBRENTEU.csv").stat().st_mtime, UTC).strftime("%Y-%m-%d")
    src = trends["sources"]["consumer"]
    out = {}
    for geo, c in trends["countries"].items():
        ser = (c.get("consumer") or {}).get("CP0722")
        fit = ser and passthrough(yoy_series(ser), brent)
        if fit:
            fit["series"] = "US CPI motor fuel (BLS via FRED)" if geo == "US" else "Eurostat HICP motor fuels (CP0722)"
            out[GEO_ISO3[geo]] = fit
    es = np.array([v["e"] for v in out.values()])
    pooled = {"e": round(float(np.median(es)), 3), "lo": round(float(np.percentile(es, 25)), 3),
              "hi": round(float(np.percentile(es, 75)), 3), "n": int(len(es))}
    return {"method": ("12-month log change in motor-fuel consumer prices on the 12-month log change in Brent (US$), "
                       f"{SAMPLE[0][:7]} to {SAMPLE[1][:7]}, Newey-West errors over {HAC_LAGS} months; range is 90%"),
            "brent": f"FRED MCOILBRENTEU (Brent, monthly average, US$), fetched {fetched}",
            "prices": f"{src['eu']}; US: {src['US']}",
            "pooled": pooled | {"what": "median of the national slopes; the range is their middle half"},
            "countries": out}


# ------------------------------------------------------------------------------------------------- trade
def comtrade(year: int, partners: str, flow: str, cmd: int) -> list[dict]:
    path = RAW / f"oil_{flow}_{cmd}_{partners.replace(',', '-')}_{year}.json"
    if not path.exists():
        md._get(CT.format(year=year, partners=partners, flow=flow, cmd=cmd), path)
        time.sleep(PAUSE)
    body = json.loads(path.read_text(encoding="utf-8"))
    if "data" not in body or body.get("count", 0) >= PREVIEW_CAP:  # quota, error or truncated: don't cache it
        path.unlink()
        sys.exit(f"Comtrade {path.name}: {body.get('message') or body.get('error') or f'{PREVIEW_CAP} rows, split the call'}")
    # keep the reporter-level totals: all transport modes, all customs procedures, no second partner
    return [r for r in body["data"] if r.get("partner2Code", 0) == 0 and r.get("motCode", 0) == 0
            and r.get("customsCode", "C00") == "C00" and r.get("primaryValue")]


def sum_by_reporter(rows: list[dict]) -> dict[int, float]:
    out: dict[int, float] = {}
    for r in rows:
        out[r["reporterCode"]] = out.get(r["reporterCode"], 0.0) + float(r["primaryValue"])
    return out


def trade_profile(imp: float, exp: float, gulf_by: dict[str, float]) -> dict:
    """Shares for one country from its oil imports, exports and imports from each Gulf producer (US$)."""
    gulf = sum(gulf_by.values())
    return {"imp": round(imp), "exp": round(exp), "gulf": round(gulf),
            "gulf_share": round(min(1.0, gulf / imp), 3) if imp > 0 else None,
            "m": round(max(-20.0, (imp - exp) / imp), 3) if imp > 0 else -20.0,
            "by": {k: round(v) for k, v in sorted(gulf_by.items(), key=lambda kv: -kv[1]) if v > 0}}


def trade_section() -> dict:
    ref = json.loads(md._get(CT_REPORTERS, RAW / "reporters.json").read_text(encoding="utf-8"))["results"]
    iso = {r["reporterCode"]: r["reporterCodeIsoAlpha3"].strip() for r in ref if not r.get("isGroup")}
    out = {}
    for year in YEARS:
        imp = sum_by_reporter([r for cmd in CMDS for r in comtrade(year, "0", "M", cmd)])
        exp = sum_by_reporter([r for cmd in CMDS for r in comtrade(year, "0", "X", cmd)])
        gulf_rows = [r for cmd in CMDS for group in GULF_CALLS for r in comtrade(year, ",".join(map(str, group)), "M", cmd)]
        for rep, total in imp.items():
            code = iso.get(rep)
            if not code or code in out:  # 2024 first; 2023 only for countries without a 2024 report
                continue
            by: dict[str, float] = {}
            for r in gulf_rows:
                if r["reporterCode"] == rep:
                    by[GULF[r["partnerCode"]]] = by.get(GULF[r["partnerCode"]], 0.0) + float(r["primaryValue"])
            out[code] = trade_profile(total, exp.get(rep, 0.0), by) | {"year": year}
    collected = datetime.fromtimestamp(min(p.stat().st_mtime for p in RAW.glob("oil_*.json")), UTC).strftime("%Y-%m-%d")
    return {"source": "UN Comtrade, public preview API (HS 2709 crude and HS 2710 refined products, imports CIF and "
                      "exports FOB as each country reports them, US$)",
            "url": "https://comtradeplus.un.org/", "collected": collected,
            "gulf": list(GULF.values()),
            "notes": ("gulf_share: imports from the seven Gulf producers / all oil imports, an upper bound for oil "
                      "through the strait (Yanbu and Fujairah bypass it); m: net oil imports / oil imports"),
            "countries": out}


# ------------------------------------------------------------------------------------------------ report
def report(d: dict) -> str:
    f, t = d.get("fuel"), d.get("trade")
    lines = ["# Country oil profiles", "",
             f"_Generated by `experiments/country_oil.py` on {d['generated']}. Nothing here is synthetic._", ""]
    if f:
        lines += ["## Fuel pass-through", "", f"{f['method']}. Brent: {f['brent']}.", "",
                  f"Pooled (for countries without a series): {f['pooled']['e']:.2f}, middle half "
                  f"{f['pooled']['lo']:.2f} to {f['pooled']['hi']:.2f} over {f['pooled']['n']} countries.", "",
                  "| Country | Slope | 90% range | R² | Months |", "|---|---|---|---|---|"]
        for k, v in sorted(f["countries"].items(), key=lambda kv: -kv[1]["e"]):
            lines.append(f"| {k} | {v['e']:.2f} | {v['lo']:.2f} to {v['hi']:.2f} | {v['r2']:.2f} | {v['n']} |")
        lines.append("")
    if t:
        c = t["countries"]
        dep = sorted(((k, v) for k, v in c.items() if v["gulf_share"] is not None and v["m"] > 0), key=lambda kv: -kv[1]["gulf_share"])
        lines += ["## Oil trade", "", f"{t['source']}, collected {t['collected']}. {t['notes']}.", "",
                  f"{len(c)} countries report oil trade; {sum(v['year'] == 2024 for v in c.values())} for 2024, "
                  f"the rest for 2023. {sum(v['m'] < 0 for v in c.values())} are net exporters by value.", "",
                  "Most Gulf-dependent importers:", "", "| Country | Year | Gulf share of oil imports | m |", "|---|---|---|---|"]
        lines += [f"| {k} | {v['year']} | {v['gulf_share']:.0%} | {v['m']:.2f} |" for k, v in dep[:25]]
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    d = json.loads(OUT_JSON.read_text(encoding="utf-8")) if OUT_JSON.exists() else {}
    if what in ("fuel", "all"):
        d["fuel"] = fuel_section()
    if what in ("trade", "all"):
        d["trade"] = trade_section()
    d = {"generated": today(), "script": "experiments/country_oil.py"} | {k: v for k, v in d.items() if k in ("fuel", "trade")}
    OUT_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_MD.write_text(report(d), encoding="utf-8")
    print("wrote", OUT_JSON, "and", OUT_MD)


if __name__ == "__main__":
    main()
