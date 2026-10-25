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
3. Cost of living, FAOSTAT consumer price indices (monthly, general and food, about 200 countries, no key):
   each country's latest inflation (12-month change, computed from the index), and how far its overall and
   food prices follow Brent at 1, 2, 3, 6 and 12 months: the h-month log change in prices on the h-month
   log change in Brent, 2009-2025, Newey-West errors over h months. A sustained Brent move of x% adds about
   slope_h * x% to prices after h months (the average link; supply disruptions can move faster). Fits too
   noisy to use (high-inflation countries) are dropped and marked.

    uv run experiments/country_oil.py fuel    # pass-through (FRED + notes/country-trends.json)
    uv run experiments/country_oil.py trade   # Comtrade pulls, cached in data/raw/comtrade-oil/
    uv run experiments/country_oil.py prices  # FAOSTAT, cached in data/raw/faostat/
    uv run experiments/country_oil.py         # all three; writes notes/country-oil.json and notes/country-oil.md
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
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
PAUSE = 8.0  # seconds between calls to the public preview
FAO_URL = "https://bulks-faostat.fao.org/production/ConsumerPriceIndices_E_All_Data_(Normalized).zip"
FAO_ZIP = md.ROOT / "data" / "raw" / "faostat" / "cpi.zip"
FAO_ITEMS = {"Consumer Prices, General Indices (2015 = 100)": "all", "Consumer Prices, Food Indices (2015 = 100)": "food"}
HORIZONS = (1, 2, 3, 6, 12)
NOISY_SE = 0.15  # a 12-month slope with a larger standard error than this is too noisy to show
OUTLOOK_FROM = "2025-10-01"  # a series whose latest month is older than this gets no outlook (it shows its date)
WIDE = np.log(4)  # a 12-month 90% band wider than a factor of 4 (in log terms) is shown as very uncertain
MAX_WIDTH = np.log(16)  # and one wider than a factor of 16 is not a forecast
MIN_MISSES = 8  # past naive forecasts needed to set a band
# FAOSTAT's M49 codes where the Comtrade reporter list (our ISO3 source) uses another code or has none
M49_FIX = {250: "FRA", 578: "NOR", 756: "CHE", 840: "USA", 158: "TWN", 630: "PRI", 316: "GUM"}
MONTH_NO = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                            "August", "September", "October", "November", "December"])}


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
    for wait in (30, 60, 120, 240, 0):  # the preview answers 429 when called too fast: back off and retry
        if path.exists():
            break
        try:
            md._get(CT.format(year=year, partners=partners, flow=flow, cmd=cmd), path)
            time.sleep(PAUSE)
        except urllib.error.HTTPError as e:
            if e.code != 429 or not wait:
                raise
            time.sleep(wait)
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


# map countries that don't report oil trade, by Comtrade partner code (Taiwan is "Other Asia, nes", 490), in small
# groups so no call reaches the preview's 500 rows; the big exporters get groups of their own
MIRROR = {"RUS": 643, "BLR": 112, "VEN": 862, "LBY": 434, "TKM": 795, "GNQ": 226, "TCD": 148, "SDN": 729, "SSD": 728,
          "SYR": 760, "AFG": 4, "BGD": 50, "NPL": 524, "PRK": 408, "TWN": 490, "KOS": 412, "CUB": 192, "HTI": 332, "PRI": 630,
          "GRL": 304, "NCL": 540, "SLB": 90, "VUT": 548, "ERI": 232, "GIN": 324, "GNB": 624, "SLE": 694, "SOM": 706}
MIRROR_GROUPS = [("RUS", "BLR"), ("VEN", "LBY", "TKM"), ("GNQ", "TCD", "SDN", "SSD", "SYR"), ("AFG", "BGD", "NPL", "PRK", "TWN", "KOS"),
                 ("CUB", "HTI", "PRI", "GRL", "NCL", "SLB", "VUT"), ("ERI", "GIN", "GNB", "SLE", "SOM")]
MIRROR_YEAR = 2023  # partners' 2023 records are the most complete


def mirror_trade(year: int = MIRROR_YEAR) -> dict:
    """Oil trade of countries that don't report it, from their partners' records: what partners say they exported
    to the country (its imports; the Gulf share from the Gulf producers that report: Iraq, Iran and Kuwait often
    don't, so it can be low) and what they say they imported from it (its exports)."""
    code_iso = {MIRROR[i]: i for g in MIRROR_GROUPS for i in g}
    imp, exp, gulf = {}, {}, {}
    for group in MIRROR_GROUPS:
        partners = ",".join(str(MIRROR[i]) for i in group)
        for cmd in CMDS:
            for r in comtrade(year, partners, "X", cmd):
                iso = code_iso.get(r["partnerCode"])
                if iso:
                    imp[iso] = imp.get(iso, 0.0) + float(r["primaryValue"])
                    if r["reporterCode"] in GULF:
                        by = gulf.setdefault(iso, {})
                        by[GULF[r["reporterCode"]]] = by.get(GULF[r["reporterCode"]], 0.0) + float(r["primaryValue"])
            for r in comtrade(year, partners, "M", cmd):
                iso = code_iso.get(r["partnerCode"])
                if iso:
                    exp[iso] = exp.get(iso, 0.0) + float(r["primaryValue"])
    return {iso: trade_profile(imp.get(iso, 0.0), exp.get(iso, 0.0), gulf.get(iso, {})) | {"year": year, "mirror": True}
            for iso in code_iso.values() if imp.get(iso) or exp.get(iso)}


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
    for iso, v in mirror_trade().items():
        out.setdefault(iso, v)
    collected = datetime.fromtimestamp(min(p.stat().st_mtime for p in RAW.glob("oil_*.json")), UTC).strftime("%Y-%m-%d")
    return {"source": "UN Comtrade, public preview API (HS 2709 crude and HS 2710 refined products, imports CIF and "
                      "exports FOB as each country reports them, US$)",
            "url": "https://comtradeplus.un.org/", "collected": collected,
            "gulf": list(GULF.values()),
            "notes": ("gulf_share: imports from the seven Gulf producers / all oil imports, an upper bound for oil "
                      "through the strait (Yanbu and Fujairah bypass it); m: net oil imports / oil imports; countries "
                      f"marked mirror don't report, so their figures are their partners' {MIRROR_YEAR} records"),
            "countries": out}


# ---------------------------------------------------------------------------------------- cost of living
def fao_levels(zip_path, m49_iso: dict[int, str]) -> dict[str, dict[str, pd.Series]]:
    """{iso3: {"all"|"food": monthly index Series}} from the FAOSTAT consumer price bulk file."""
    import csv, io, zipfile  # noqa: E401
    with zipfile.ZipFile(zip_path) as z, z.open("ConsumerPriceIndices_E_All_Data_(Normalized).csv") as f:
        rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="latin-1")))
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        kind = FAO_ITEMS.get(r["Item"])
        iso = m49_iso.get(int(r["Area Code (M49)"].strip("'")))
        if not kind or not iso or r["Months"] not in MONTH_NO or not r["Value"]:
            continue
        out.setdefault(iso, {}).setdefault(kind, {})[pd.Timestamp(int(r["Year"]), MONTH_NO[r["Months"]], 1)] = float(r["Value"])
    return {iso: {k: pd.Series(v).sort_index() for k, v in d.items()} for iso, d in out.items()}


def horizon_link(level: pd.Series, brent: pd.Series, h: int, sample=SAMPLE) -> dict | None:
    """Slope of the h-month log change in a price index on the h-month log change in Brent."""
    y = 100 * np.log(level).diff(h)
    x = 100 * np.log(brent).diff(h)
    d = pd.DataFrame({"y": y, "x": x}).loc[sample[0]:sample[1]].dropna()
    if len(d) < 60:
        return None
    X = np.column_stack([np.ones(len(d)), d["x"].to_numpy()])
    b, se = ols_hac(d["y"].to_numpy(), X, h)
    return {"b": round(float(b[1]), 4), "se": round(float(se[1]), 4)}


def latest_yoy(level: pd.Series, at: str | None = None) -> dict | None:
    """12-month % change at the latest month, or at month `at` (YYYY-MM)."""
    s = level[level > 0]
    t = pd.Timestamp(at + "-01") if at else (s.index[-1] if len(s) else None)
    if t is None or t not in s.index:
        return None
    prev = s.get(t - pd.DateOffset(months=12))
    return None if prev is None else {"v": round(100 * (s[t] / prev - 1), 1), "month": t.strftime("%Y-%m")}


COL_RESPONSES = md.ROOT / "notes" / "cost-of-living-responses.csv"
FOOD_KINDS = ("bread", "dairy", "meat", "fruit_veg", "oils_fats", "sugar")


def model_prior(path=COL_RESPONSES, horizons=HORIZONS) -> dict[str, dict[str, float]]:
    """Our cost-of-living model's oil link as a prior: its normal-regime response of all prices and of food
    (the food items weighted by their basket weights) to a sustained +10% Brent move, averaged over the US,
    the UK and the euro area, per 1% log move: {"all"|"food": {h: slope}}."""
    import csv  # noqa: E401
    rows = [r for r in csv.DictReader(path.open(encoding="utf-8")) if r["regime"] == "normal" and int(r["months_ahead"]) in horizons]
    per10 = 100 * np.log(1.1)
    out: dict[str, dict[str, float]] = {"all": {}, "food": {}}
    for h in horizons:
        at = [r for r in rows if int(r["months_ahead"]) == h]
        alls = [float(r["q50"]) for r in at if r["kind"] == "all" and r["region"] in ("us", "uk", "ea")]
        food = []
        for reg in ("us", "uk", "ea"):
            items = [r for r in at if r["region"] == reg and r["kind"] in FOOD_KINDS and float(r["weight"] or 0) > 0]
            if items:
                food.append(sum(float(r["q50"]) * float(r["weight"]) for r in items) / sum(float(r["weight"]) for r in items))
        out["all"][str(h)] = round(float(np.mean(alls)) / per10, 4)
        out["food"][str(h)] = round(float(np.mean(food)) / per10, 4)
    return out


def partial_pool(fits: dict[str, dict], prior: float | None = None) -> tuple[dict[str, dict], dict]:
    """Shrink each country's slope towards a prior by how noisy it is: a ridge update, b = (b_ols/se² + prior/tau²) /
    (1/se² + 1/tau²), with tau the spread of the true slopes around the prior, estimated from the countries.
    Without a prior, the prior is the cross-country mean (empirical Bayes).
    {iso: {b, se}} -> ({iso: {b, se}} updated, {b: prior, se: tau})."""
    b = np.array([f["b"] for f in fits.values()])
    s2 = np.array([f["se"] ** 2 for f in fits.values()])
    if prior is None:
        tau2 = max(float(np.var(b) - np.mean(s2)), 1e-8)
        w = 1 / (s2 + tau2)
        mu = float(np.sum(w * b) / np.sum(w))
    else:
        mu = prior
        tau2 = max(float(np.mean((b - mu) ** 2) - np.mean(s2)), 1e-8)
    out = {}
    for iso, f in fits.items():
        prec = 1 / f["se"] ** 2 + 1 / tau2
        out[iso] = {"b": round((f["b"] / f["se"] ** 2 + mu / tau2) / prec, 4), "se": round(float(np.sqrt(1 / prec)), 4)}
    return out, {"b": round(mu, 4), "se": round(float(np.sqrt(tau2)), 4)}


def outlook(level: pd.Series, brent: pd.Series, horizons=HORIZONS, sims=2000, seed=0, until=None) -> dict | None:
    """Forecast of a monthly price index from its latest month (or from `until`, for backtests).
    Monthly log change on its own last month, month-of-year effects and Brent's change this month and the
    two before, fitted from 2009 to the origin. Brent's known changes after the origin are used (prices are
    published later than Brent), then Brent is held flat; with `until`, Brent is flat from the origin. The
    band simulates the model's own errors (bootstrap). Returns {h: [q05, q50, q95]}: % change in the index
    after h months, and the origin month."""
    y = 100 * np.log(level[level > 0]).diff()
    if until:
        y = y.loc[:until]
    b = 100 * np.log(brent).diff()
    d = pd.DataFrame({"y": y, "y1": y.shift(1), "b0": b, "b1": b.shift(1), "b2": b.shift(2)}).loc["2009-01-01":].dropna()
    if len(d) < 96:
        return None
    month = d.index.month
    X = np.column_stack([np.ones(len(d)), d[["y1", "b0", "b1", "b2"]].to_numpy()] + [(month == m).astype(float) for m in range(2, 13)])
    coef, *_ = np.linalg.lstsq(X, d["y"].to_numpy(), rcond=None)
    resid = d["y"].to_numpy() - X @ coef
    last, t0 = float(y.dropna().iloc[-1]), y.dropna().index[-1]
    known = b.loc[:t0] if until else b  # Brent changes the forecast may use
    bk = lambda t: float(known.get(t, 0.0)) if t in known.index and np.isfinite(known.get(t, np.nan)) else 0.0  # noqa: E731
    rng = np.random.default_rng(seed)
    H = max(horizons)
    paths = np.zeros((sims, H))
    prev = np.full(sims, last)
    for k in range(H):
        t = t0 + pd.DateOffset(months=k + 1)
        season = coef[5 + t.month - 2] if t.month >= 2 else 0.0
        oil = coef[2] * bk(t) + coef[3] * bk(t - pd.DateOffset(months=1)) + coef[4] * bk(t - pd.DateOffset(months=2))
        step = coef[0] + coef[1] * prev + season + oil + (rng.choice(resid, sims) if sims > 1 else 0.0)
        paths[:, k] = step
        prev = step
    cum = np.cumsum(paths, axis=1)
    q = {h: [round(float(100 * (np.exp(np.percentile(cum[:, h - 1], p) / 100) - 1)), 2) for p in (5, 50, 95)] for h in horizons}
    return {"from": t0.strftime("%Y-%m"), "q": {str(h): v for h, v in q.items()}}


def backtest(level: pd.Series, brent: pd.Series, h: int = 12) -> list[tuple[float, float]]:
    """(model error, naive error) in points, for h-month-ahead forecasts from origins every 6 months
    2015-2024. Naive: the last 12 months' inflation continues. The model's forecast is its mean path."""
    s = level[level > 0]
    out = []
    for origin in pd.date_range("2015-06-01", "2024-06-01", freq="6MS"):
        end, back = origin + pd.DateOffset(months=h), origin - pd.DateOffset(months=12)
        if not all(t in s.index for t in (origin, end, back)):
            continue
        f = outlook(s, brent, horizons=(h,), sims=1, until=origin)
        if not f:
            continue
        actual = 100 * (s[end] / s[origin] - 1)
        naive = 100 * ((s[origin] / s[back]) ** (h / 12) - 1)
        out.append((abs(f["q"][str(h)][1] - actual), abs(naive - actual), actual - naive))
    return out


def naive_outlook(level: pd.Series, brent: pd.Series, link: dict | None, misses: list[float], horizons=HORIZONS) -> dict | None:
    """What the backtests support: the latest 12 months' inflation continues, plus the country's oil link
    applied to Brent's known move since the latest price month. The 90% band is the spread of this
    country's past 12-month misses of the naive rule, in log terms (so it scales with high inflation and
    never goes below -100%), scaled by sqrt(h/12). Returns % changes [q05, q50, q95, oil part] by horizon."""
    s = level[level > 0]
    t0 = s.index[-1]
    back = t0 - pd.DateOffset(months=12)
    if back not in s.index or len(misses) < MIN_MISSES:
        return None
    g = np.log(s[t0] / s[back])  # the latest 12 months, as a log change
    lo, hi = np.percentile(misses, [5, 95])
    lb = np.log(brent.dropna())
    out = {}
    for h in horizons:
        t = min(t0 + pd.DateOffset(months=h), lb.index[-1])
        oil = (link[str(h)]["b"] * (lb[t] - lb[t0])) if link and t0 in lb.index and t > t0 else 0.0  # log points
        mid, k = g * h / 12 + oil, np.sqrt(h / 12)
        pc = lambda x: round(float(100 * (np.exp(x) - 1)), 2)  # noqa: E731
        out[str(h)] = [pc(mid + lo * k), pc(mid), pc(mid + hi * k), round(float(100 * oil), 2)]
    return {"from": t0.strftime("%Y-%m"), "q": out, "width12": round(float(hi - lo), 3)}


IMF_URL = ("https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/CPI/+/*.CPI.{coicop}.{measure}.{freq}"
           "?c%5BTIME_PERIOD%5D=ge:2005-01")
IMF_RAW = md.ROOT / "data" / "raw" / "imf"
# IMF CPI divisions (COICOP 1999): all items, food, housing and energy (rent, water, electricity, gas, fuels), transport
IMF_KINDS = {"all": "_T", "food": "CP01", "energy": "CP04", "transport": "CP07"}


def imf_cpi(coicop: str, measure: str = "IX", freq: str = "M") -> dict[str, pd.Series]:
    """{iso3: Series} from the IMF's CPI dataset (SDMX 3.0 JSON, no key), monthly or quarterly periods."""
    path = md._get(IMF_URL.format(coicop=coicop, measure=measure, freq=freq), IMF_RAW / f"cpi_{coicop}_{measure}_{freq.replace('*', 'all')}.json")
    d = json.loads(path.read_text(encoding="utf-8"))["data"]
    st = d["structures"][0]
    dims, times = st["dimensions"]["series"], [v["value"] for v in st["dimensions"]["observation"][0]["values"]]

    def when(t):
        y, p = t.split("-")
        return pd.Timestamp(int(y), int(p[1:]) if p[0] == "M" else 3 * int(p[1:]), 1)

    out = {}
    for key, ser in d["dataSets"][0].get("series", {}).items():
        iso = dims[0]["values"][int(key.split(":")[0])]["id"]
        vals = {when(times[int(i)]): float(o[0]) for i, o in ser.get("observations", {}).items() if o and o[0] not in (None, "")}
        if vals:
            out[iso] = pd.Series(vals).sort_index()
    return out


def naive_misses(level: pd.Series, h: int = 12) -> list[float]:
    """What happened minus the naive rule ('the last 12 months' rate continues'), h months ahead, in log terms,
    from origins every 6 months 2015-2024: the spread of these sets the outlook's band."""
    s = level[level > 0]
    out = []
    for origin in pd.date_range("2015-06-01", "2024-06-01", freq="6MS"):
        end, back = origin + pd.DateOffset(months=h), origin - pd.DateOffset(months=12)
        if all(t in s.index for t in (origin, end, back)):
            out.append(float(np.log(s[end] / s[origin]) - h / 12 * np.log(s[origin] / s[back])))
    return out


def prices_section() -> dict:
    ref = json.loads(md._get(CT_REPORTERS, RAW / "reporters.json").read_text(encoding="utf-8"))["results"]
    m49_iso = {r["reporterCode"]: r["reporterCodeIsoAlpha3"].strip() for r in ref if not r.get("isGroup")} | M49_FIX
    fao = fao_levels(md._get(FAO_URL, FAO_ZIP), m49_iso)
    imf = {kind: imf_cpi(code) for kind, code in IMF_KINDS.items()}
    # each household budget's shares (% of spending) on food, housing and energy, and transport, latest year
    weights = {}
    for kind, code in IMF_KINDS.items():
        if kind != "all":
            for iso, w in imf_cpi(code, "WGT_PT", "*").items():
                weights.setdefault(iso, {})[kind] = round(float(w.iloc[-1]), 1)
    brent = md.fetch_fred("MCOILBRENTEU")
    # candidates for each country and division: the IMF first (months to Sep 2026), then FAOSTAT; the first one that
    # is recent and long enough to test the forecast on is used, else the first one is shown with the reason
    cands: dict[str, dict[str, list[tuple[pd.Series, str]]]] = {}
    for kind, by in imf.items():
        for iso, s in by.items():
            cands.setdefault(iso, {}).setdefault(kind, []).append((s, "IMF"))
    for iso, d in fao.items():
        for kind, s in d.items():
            cands.setdefault(iso, {}).setdefault(kind, []).append((s, "FAOSTAT"))
    usable = lambda s: s.index[-1] >= pd.Timestamp(OUTLOOK_FROM) and len(naive_misses(s)) >= MIN_MISSES  # noqa: E731
    out, noisy, raw, errs = {}, [], {}, {}
    for iso, d in sorted(cands.items()):
        c = {}
        for kind, options in d.items():
            level, src = next((o for o in options if usable(o[0])), options[0])
            links = {h: horizon_link(level, brent, h) for h in HORIZONS}
            ok = all(links.values()) and links[12]["se"] <= NOISY_SE
            if not ok and links[12] is not None:
                noisy.append(f"{iso} {kind}")
            if ok:
                for h, f in links.items():
                    raw.setdefault((kind, h), {})[iso] = f
            # the time-series model's backtest (it lost to the naive rule) is kept for all prices and food only
            if ok and kind in ("all", "food") and src == "FAOSTAT":
                errs.setdefault(kind, []).extend(backtest(level, brent))
            # inflation now, and in Feb 2026, the last month before the Hormuz closure
            c[kind] = {"now": latest_yoy(level), "before": latest_yoy(level, "2026-02"), "link": None, "own": ok, "src": src,
                       "misses": naive_misses(level), "level": level}
        out[iso] = c
    # Kosovo isn't in the IMF's or FAO's data; the trends data has its HICP (annual rates only)
    xk = json.loads(TRENDS.read_text(encoding="utf-8"))["countries"].get("XK", {}).get("consumer", {})
    for kind, code in (("all", "TOTAL"), ("food", "CP01")):
        ser = yoy_series(xk[code]).dropna() if code in xk else None
        if ser is not None and len(ser):
            out.setdefault("KOS", {})[kind] = {"now": {"v": round(float(ser.iloc[-1]), 1), "month": ser.index[-1].strftime("%Y-%m")},
                                              "before": None, "link": None, "own": False, "src": "Eurostat HICP", "misses": [], "level": None}
    # ridge update of each country's link: towards our cost-of-living model for all prices and food, towards the
    # cross-country average for housing and energy, and transport (our model has no such composites)
    prior = model_prior()
    pooled = {}
    for (kind, h), fits in raw.items():
        shrunk, pooled.setdefault(kind, {})[str(h)] = partial_pool(fits, prior[kind][str(h)] if kind in prior else None)
        for iso, f in shrunk.items():
            out[iso][kind]["link"] = (out[iso][kind]["link"] or {}) | {str(h): f | {"own": fits[iso]["b"]}}
    # the outlook needs the links, so it comes last; a country too unstable to fit gets the prior's link
    for c in out.values():
        for kind, v in c.items():
            level, misses = v.pop("level"), v.pop("misses")
            link = v["link"] or ({str(h): {"b": pooled[kind][str(h)]["b"]} for h in HORIZONS} if kind in pooled else None)
            fresh = level is not None and level.index[-1] >= pd.Timestamp(OUTLOOK_FROM)
            o = naive_outlook(level, brent, link, misses) if fresh else None
            # a band wider than a factor of 16 over a year is no forecast; wider than 4 is shown, marked very uncertain
            v["outlook"] = o if o and o["width12"] <= MAX_WIDTH else None
            v["uncertain"] = bool(v["outlook"] and o["width12"] > WIDE)
            v["why_none"] = (None if v["outlook"] else "annual rates only" if level is None
                             else "its latest month is too old to forecast from" if not fresh
                             else "too few past months to test a forecast on" if len(misses) < MIN_MISSES
                             else "prices too erratic to forecast")
    fetched = datetime.fromtimestamp(FAO_ZIP.stat().st_mtime, UTC).strftime("%Y-%m-%d")
    imf_fetched = datetime.fromtimestamp(min(p.stat().st_mtime for p in IMF_RAW.glob("cpi_*.json")), UTC).strftime("%Y-%m-%d")
    return {"source": (f"IMF consumer price indices by COICOP division (all items, food, housing and energy, transport; "
                       f"monthly; budget weights), fetched {imf_fetched}; FAOSTAT consumer price indices (general and food) "
                       f"where the IMF has none, fetched {fetched}"),
            "url": "https://data.imf.org/ (CPI); https://www.fao.org/faostat/en/#data/CP",
            "weights": weights,
            "method": ("h-month log change in the price index on the h-month log change in Brent (FRED MCOILBRENTEU, US$), "
                       f"{SAMPLE[0][:7]} to {SAMPLE[1][:7]}, Newey-West errors over h months; each country's slope is "
                       "ridge-updated towards our cost-of-living model's link for all prices and food (US, UK and euro-area "
                       "average, normal regime) and towards the cross-country average for housing and energy, and transport, "
                       "by its noise, the penalty set by how far the countries' true slopes spread around the model; "
                       "inflation is the 12-month change in the index, at the latest month and in Feb 2026 before the closure"),
            "prior": prior,
            "outlook": ("the latest 12 months' inflation continues, plus the country's oil link applied to Brent's known "
                        "move since the latest price month; 90% band from this country's past misses of that rule "
                        "(12-month forecasts from every 6 months, 2015-2024), scaled by the square root of the horizon"),
            # a per-country time-series model (own last month, month of year, Brent's last three months) was
            # tried first and lost to the naive rule in the same backtest, so the outlook above uses the rule
            "ar_skill": {k: {"vs_naive": round(1 - sum(e[0] for e in v) / sum(e[1] for e in v), 2), "forecasts": len(v),
                             "what": "12-month-ahead error of the time-series model against 'the last 12 months' inflation continues', origins every 6 months 2015-2024"}
                         for k, v in errs.items()},
            "horizons": list(HORIZONS), "pooled": pooled, "noisy": noisy, "countries": out}


# ------------------------------------------------------------------------------------------------ report
def report(d: dict) -> str:
    f, t, p = d.get("fuel"), d.get("trade"), d.get("prices")
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
    if p:
        c = p["countries"]
        lines += ["## Cost of living", "", f"{p['source']}. Oil links: {p['method']}.", "",
                  f"{len(c)} countries; too unstable to fit (very high inflation): {', '.join(p['noisy']) or 'none'}.", "",
                  "Pooled link (% price change per 1% Brent move over the same months, and the spread of the true slopes):", "",
                  "| Prices | " + " | ".join(f"{h} mo" for h in p["horizons"]) + " |", "|---|" + "---|" * len(p["horizons"])]
        for kind, v in p["pooled"].items():
            lines.append(f"| {kind} | " + " | ".join(f"{v[str(h)]['b']:+.4f} (±{v[str(h)]['se']:.4f})" for h in p["horizons"]) + " |")
        lines += ["", f"Outlook: {p['outlook']}.", "",
                  "A per-country time-series model (its own last month, month of year, Brent's last three months) was tried "
                  "first and lost to the naive rule in the same backtest: skill against naive "
                  + ", ".join(f"{k} {v['vs_naive']:+.2f} over {v['forecasts']} forecasts" for k, v in p["ar_skill"].items())
                  + ". So the outlook uses the naive rule plus the oil link.", ""]
    return "\n".join(lines)


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    d = json.loads(OUT_JSON.read_text(encoding="utf-8")) if OUT_JSON.exists() else {}
    if what in ("fuel", "all"):
        d["fuel"] = fuel_section()
    if what in ("trade", "all"):
        d["trade"] = trade_section()
    if what in ("prices", "all"):
        d["prices"] = prices_section()
    d = {"generated": today(), "script": "experiments/country_oil.py"} | {k: v for k, v in d.items() if k in ("fuel", "trade", "prices")}
    OUT_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_MD.write_text(report(d), encoding="utf-8")
    print("wrote", OUT_JSON, "and", OUT_MD)


if __name__ == "__main__":
    main()
