# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "xlrd>=2.0", "openpyxl>=3.1"]
# ///
"""Monthly macro panel for the knock-on models: oil, AIS flows, regions (US, UK, euro area), industry;
and, for the sector runs, industries by country and world metal prices (SECTOR_BLOCKS).

Every series is registered once in SERIES with its source, its transform, how many months after the
month it describes it is published (`lag`, so a forecast made at the end of month t only sees what
was public then) and, for targets, what is forecast. Blocks are switched on by name, so a region
is added by adding its rows.

Sources (all free, no keys):
  FRED (St. Louis Fed)            fredgraph CSV
  ONS (UK)                        time-series CSV generator
  Eurostat                        statistics API (JSON-stat)
  IMF PortWatch                   daily chokepoint transits from AIS (ArcGIS feature service), 2019 on
  Caldara & Iacoviello            geopolitical risk index (monthly XLS)
  UNDP                            Human Development Index (annual CSV; see hdi_link.py)
Industry series are read from notes/industry/fred_series.csv (Eileen's list), not copied. The sector
rows (industry x country) are generated from SECTORS and COUNTRIES.

    uv run experiments/macro_data.py   # fetches everything into data/raw/, writes notes/macro-panel.md
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "macro"
INDUSTRY_LIST = ROOT / "notes" / "industry" / "fred_series.csv"
OUT = ROOT / "notes" / "macro-panel.md"
START = "2000-01-01"
MAX_FILL = 3  # months a gap may be forward-filled (e.g. the missing October 2025 US releases)
SHARE_BASE = ("2019-01-01", "2024-12-31")  # "normal" flow for the AIS share-of-normal features
UA = {"User-Agent": "oxhack26-research (github.com/Alex-Sebastian-Ene/oxhack)"}

PORTWATCH = ("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
             "Daily_Chokepoints_Data/FeatureServer/0/query")
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{}?{}"
ONS = "https://www.ons.gov.uk/generator?format=csv&uri={}"
GPR_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"
GSCPI_URL = "https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx"
PORTWATCH_PORTS = ("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
                   "Daily_Ports_Data/FeatureServer/0/query")


@dataclass(frozen=True)
class Series:
    key: str  # panel column stem
    source: str  # fred | ons | eurostat | portwatch | gpr
    code: str  # id at the source
    block: str  # oil | ais | us | uk | ea | industry
    transform: str  # dlog | diff | level | level+diff
    lag: int  # months between the end of the month described and publication
    target: str | None = None  # inflation | unemployment | rate | cost, or None for inputs only
    name: str = ""
    freq: str = "M"  # M, or Q for quarterly (placed at the quarter's last month before the lag)
    anchor_lags: int | None = None  # oil lags (months) in the target's linear pass-through; None = by kind


SERIES = [
    # Oil market: prices, demand signal, geopolitical risk.
    Series("brent", "fred", "DCOILBRENTEU", "oil", "dlog", 0, name="Brent spot, $/bbl (EIA)"),
    Series("wti", "fred", "DCOILWTICO", "oil", "dlog", 0, name="WTI spot, $/bbl (EIA)"),
    Series("igrea", "fred", "IGREA", "oil", "level+diff", 1, name="Global real economic activity (Kilian)"),
    Series("gpr", "gpr", "GPR", "oil", "level+diff", 0, name="Geopolitical risk index (Caldara & Iacoviello)"),
    # AIS: tanker transits and capacity through chokepoints (IMF PortWatch, from 2019).
    # "share": flow as a fraction of its 2019-2024 average, which stays readable through a closure
    # (a log change would be -4 when Hormuz tanker capacity fell 98% in March 2026).
    Series("hormuz_tankers", "portwatch", "chokepoint6:n_tanker", "ais", "share", 0,
           name="Strait of Hormuz tanker transits per day (PortWatch, AIS)"),
    Series("hormuz_capacity", "portwatch", "chokepoint6:capacity_tanker", "ais", "share", 0,
           name="Strait of Hormuz tanker capacity per day, dwt (PortWatch, AIS)"),
    Series("babelmandeb_capacity", "portwatch", "chokepoint4:capacity_tanker", "ais", "share", 0,
           name="Bab el-Mandeb tanker capacity per day, dwt (PortWatch, AIS)"),
    Series("cape_capacity", "portwatch", "chokepoint7:capacity_tanker", "ais", "share", 0,
           name="Cape of Good Hope tanker capacity per day, dwt (PortWatch, AIS)"),
    # United States.
    Series("us_cpi", "fred", "CPIAUCSL", "us", "dlog", 1, "inflation", "US CPI, all items (BLS)"),
    Series("us_core", "fred", "CPILFESL", "us", "dlog", 1, name="US CPI less food and energy (BLS)"),
    Series("us_unemp", "fred", "UNRATE", "us", "level+diff", 1, "unemployment", "US unemployment rate (BLS)"),
    Series("us_rate", "fred", "FEDFUNDS", "us", "level+diff", 0, "rate", "Effective fed funds rate (Fed)"),
    Series("us_10y", "fred", "DGS10", "us", "diff", 0, name="US 10-year Treasury yield (Fed)"),
    Series("us_ip", "fred", "INDPRO", "us", "dlog", 1, name="US industrial production (Fed)"),
    Series("us_payrolls", "fred", "PAYEMS", "us", "dlog", 1, name="US nonfarm payrolls (BLS)"),
    Series("us_sentiment", "fred", "UMCSENT", "us", "diff", 1, name="Michigan consumer sentiment"),
    Series("us_ppi", "fred", "PPIACO", "us", "dlog", 1, name="US PPI, all commodities (BLS)"),
    Series("us_productivity", "fred", "OPHNFB", "us", "dlog", 2, name="US output per hour, nonfarm business (BLS)",
           freq="Q"),
    # United Kingdom.
    Series("uk_cpi", "ons", "/economy/inflationandpriceindices/timeseries/d7bt/mm23", "uk", "dlog", 1,
           "inflation", "UK CPI index, all items (ONS D7BT)"),
    Series("uk_unemp", "fred", "LRHUTTTTGBM156S", "uk", "level+diff", 2, "unemployment",
           "UK unemployment rate (OECD via FRED)"),
    Series("uk_rate", "fred", "IUDSOIA", "uk", "level+diff", 0, "rate",
           "SONIA overnight rate (Bank of England via FRED), stands in for Bank Rate"),
    Series("uk_10y", "fred", "IRLTLT01GBM156N", "uk", "diff", 1, name="UK 10-year government bond yield (OECD)"),
    Series("uk_ip", "ons", "/economy/economicoutputandproductivity/output/timeseries/k222/diop", "uk", "dlog", 2,
           name="UK index of production (ONS K222)"),
    Series("uk_productivity", "ons", "/employmentandlabourmarket/peopleinwork/labourproductivity/timeseries/lzvb/prdy",
           "uk", "dlog", 2, name="UK output per hour worked (ONS LZVB)", freq="Q"),
    Series("gbpusd", "fred", "DEXUSUK", "uk", "dlog", 0, name="US dollars per pound (Fed)"),
    # Euro area.
    Series("ea_cpi", "fred", "CP0000EZ19M086NEST", "ea", "dlog", 1, "inflation", "Euro-area HICP (Eurostat via FRED)"),
    Series("ea_unemp", "eurostat", "une_rt_m?geo=EA21&s_adj=SA&age=TOTAL&unit=PC_ACT&sex=T&freq=M", "ea",
           "level+diff", 1, "unemployment", "Euro-area unemployment rate, EA21 (Eurostat une_rt_m)"),
    Series("ea_rate", "fred", "ECBDFR", "ea", "level+diff", 0, "rate", "ECB deposit facility rate (ECB via FRED)"),
    Series("ea_ip", "eurostat", "sts_inpr_m?geo=EA20&s_adj=SCA&unit=I21&nace_r2=B-D&indic_bt=PRD&freq=M", "ea",
           "dlog", 2, name="Euro-area industrial production, EA20 (Eurostat sts_inpr_m)"),
    Series("eurusd", "fred", "DEXUSEU", "ea", "dlog", 0, name="US dollars per euro (Fed)"),
    # Fuel flows and stocks (EIA weekly, no key needed), US.
    Series("crude_stocks", "eia", "WCESTUS1", "fuel", "dlog", 0, name="US crude stocks excluding SPR (EIA)"),
    Series("spr", "eia", "WCSSTUS1", "fuel", "dlog", 0, name="US Strategic Petroleum Reserve stocks (EIA)"),
    Series("refinery_util", "eia", "WPULEUS3", "fuel", "level+diff", 0, name="US refinery utilisation, % (EIA)"),
    Series("gasoline_demand", "eia", "WGFUPUS2", "fuel", "dlog", 0, name="US gasoline product supplied (EIA)"),
    Series("distillate_demand", "eia", "WDIUPUS2", "fuel", "dlog", 0, name="US distillate product supplied (EIA)"),
    Series("crude_imports", "eia", "WCEIMUS2", "fuel", "dlog", 0, name="US crude oil imports (EIA)"),
    Series("crude_output", "eia", "WCRFPUS2", "fuel", "dlog", 0, name="US crude oil production (EIA)"),
    # Pipelines around Hormuz, seen from AIS: tanker exports at the pipelines' sea ends against exports
    # from ports inside the Gulf (IMF PortWatch daily ports data, from 2019).
    Series("bypass_exports", "ports", "port570,port362", "pipeline", "share", 0,
           name="Tanker exports from Yanbu (East-West pipeline) and Fujairah (Habshan-Fujairah pipeline)"),
    Series("gulf_exports", "ports", "port526,port1091,port2479,port24,port512,port2237,port1341", "pipeline", "share",
           0, name="Tanker exports from ports inside the Gulf (Juaymah, Ras Tanura, Basrah, Jubail, Ruwais, Das, Umm Qasr)"),
    # Other drivers of inflation.
    Series("gscpi", "gscpi", "GSCPI", "drivers", "level+diff", 1, name="Global supply chain pressure index (NY Fed)"),
    Series("food", "fred", "PFOODINDEXM", "drivers", "dlog", 1, name="IMF all-food price index"),
    Series("us_gas", "fred", "DHHNGSP", "drivers", "dlog", 0, name="Henry Hub natural gas spot (EIA)"),
    Series("eu_gas", "fred", "PNGASEUUSDM", "drivers", "dlog", 1, name="EU natural gas price (IMF)"),
    Series("infl_expect", "fred", "MICH", "drivers", "level+diff", 0, name="Michigan 1-year inflation expectations"),
    Series("m2", "fred", "M2SL", "drivers", "dlog", 1, name="US M2 money stock (Fed)"),
    Series("import_prices", "fred", "IR", "drivers", "dlog", 1, name="US import price index (BLS)"),
    Series("shelter", "fred", "CUSR0000SAH1", "drivers", "dlog", 1, name="US CPI shelter (BLS)"),
    Series("wages", "fred", "ECIWAG", "drivers", "dlog", 2, name="US employment cost index, wages (BLS)", freq="Q"),
    # World mineral and metal prices (IMF primary commodity prices via FRED, monthly averages):
    # targets of the sector runs (experiments/sector_global.py), not of the macro models.
    Series("copper", "fred", "PCOPPUSDM", "commodities", "dlog", 1, "commodity", "Copper, $/t (IMF via FRED)"),
    Series("aluminium", "fred", "PALUMUSDM", "commodities", "dlog", 1, "commodity", "Aluminium, $/t (IMF via FRED)"),
    Series("nickel", "fred", "PNICKUSDM", "commodities", "dlog", 1, "commodity", "Nickel, $/t (IMF via FRED)"),
    Series("zinc", "fred", "PZINCUSDM", "commodities", "dlog", 1, "commodity", "Zinc, $/t (IMF via FRED)"),
    Series("lead", "fred", "PLEADUSDM", "commodities", "dlog", 1, "commodity", "Lead, $/t (IMF via FRED)"),
    Series("tin", "fred", "PTINUSDM", "commodities", "dlog", 1, "commodity", "Tin, $/t (IMF via FRED)"),
    Series("iron_ore", "fred", "PIORECRUSDM", "commodities", "dlog", 1, "commodity", "Iron ore, $/t (IMF via FRED)"),
    Series("coal", "fred", "PCOALAUUSDM", "commodities", "dlog", 1, "commodity", "Coal, Australia, $/t (IMF via FRED)"),
    Series("uranium", "fred", "PURANUSDM", "commodities", "dlog", 1, "commodity", "Uranium, $/lb (IMF via FRED)"),
]
BLOCKS = ("oil", "ais", "pipeline", "fuel", "drivers", "us", "uk", "ea", "industry")
SECTOR_BLOCKS = ("oil", "sectors", "commodities")  # the sector runs: industries by country, world metal prices
ALL_BLOCKS = BLOCKS + SECTOR_BLOCKS[1:]
MASKED = ("ais", "pipeline")  # blocks that start late (2019) and get an availability flag

# Industries by country (the `sectors` block): producer prices and output of mining, refining, metals
# and other energy-heavy industries. Eurostat covers the European countries (NACE Rev. 2); the US
# series are the closest NAICS industries on FRED (BLS PPIs, Fed industrial production), which do
# not match NACE exactly (US "smelting and refining" excludes aluminium, for example).
SECTORS = [  # (NACE code, industry, US PPI on FRED, US industrial production on FRED)
    ("B05", "Coal mining", "PCU21212121", "IPN2121S"),
    ("B06", "Crude oil and gas extraction", "PCU211211", "IPG211S"),
    ("B07", "Metal ore mining", "PCU21222122", "IPG2122S"),
    ("B08", "Other mining and quarrying", "PCU21232123", "IPG2123S"),
    ("C", "Manufacturing, total", "PCUOMFGOMFG", "IPMAN"),
    ("C17", "Paper", "PCU322322", "IPG322S"),
    ("C19", "Oil refining (coke and refined petroleum)", "PCU324324", "IPG324S"),
    ("C20", "Chemicals", "PCU325325", "IPG325S"),
    ("C2015", "Fertilisers", "PCU32533253", "IPG3253S"),
    ("C22", "Rubber and plastics", "PCU326326", "IPG326S"),
    ("C23", "Glass, cement and ceramics", "PCU327327", "IPG327S"),
    ("C235", "Cement and lime", "PCU327310327310", "IPG3273S"),
    ("C24", "Basic metals", "PCU331331", "IPG331S"),
    ("C241", "Iron and steel", "PCU331110331110", "IPG3311A2S"),
    ("C244", "Non-ferrous metal refining and smelting", "PCU331410331410", "IPG3314S"),
    ("C2442", "Aluminium", "PCU33133313", "IPG3313S"),
    ("C2443", "Lead, zinc and tin", None, None),
    ("C2444", "Copper", "PCU331420331420", None),
    ("C245", "Foundries", "PCU33153315", "IPG3315S"),
    ("D35", "Electricity and gas supply", "PCU22112211", "IPG2211S"),
]
COUNTRIES = {  # Eurostat geo codes; aggregates (EU27, EA20) are left out so no country counts twice
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany",
    "DK": "Denmark", "EE": "Estonia", "EL": "Greece", "ES": "Spain", "FI": "Finland", "FR": "France",
    "HR": "Croatia", "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LT": "Lithuania", "LU": "Luxembourg",
    "LV": "Latvia", "MT": "Malta", "NL": "Netherlands", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
    "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia", "NO": "Norway", "CH": "Switzerland", "IS": "Iceland",
    "UK": "United Kingdom", "TR": "Türkiye", "RS": "Serbia", "MK": "North Macedonia", "BA": "Bosnia and Herzegovina",
    "ME": "Montenegro", "AL": "Albania",
}
# Producer prices: domestic market, not seasonally adjusted (prices barely are). Output: volume
# index, seasonally and calendar adjusted. Both are 2021 = 100. Most countries' latest month on
# 2026-10-24 was 2026-08, so both are published two months on.
EUROSTAT_SECTORS = {"price": "sts_inppd_m?unit=I21&s_adj=NSA&indic_bt=PRC_PRR_DOM&freq=M",
                    "output": "sts_inpr_m?unit=I21&s_adj=SCA&indic_bt=PRD&freq=M"}
SECTOR_MIN_MONTHS, SECTOR_LIVE_FROM = 120, "2025-01-01"  # a generated sector row needs both to enter the panel


def industry_series() -> list[Series]:
    """Industry cost targets from Eileen's list: fuel (industry), freight, materials and industry PPIs."""
    rows = pd.read_csv(INDUSTRY_LIST)
    rows = rows[(rows["chain"] == "industry") & rows["layer"].isin(["fuel", "freight", "materials", "industry"])]
    # Pass-through lags follow notes/industry/README.md: 0-2 months for fuel and freight (and the
    # two direct "industry" series, refineries and air fares), 0-12 for materials.
    return [Series(f"ind_{r.fred_id.lower()}", "fred", r.fred_id, "industry", "dlog",
                   0 if r.frequency in ("daily", "weekly") else 1, "cost", r.name,
                   anchor_lags=12 if r.layer == "materials" else 2) for r in rows.itertuples()]


def sector_series() -> list[Series]:
    """Producer prices (target "price") and output (target "output") of every SECTORS industry in
    every country: Eurostat for COUNTRIES, FRED for the US. Pairs a country doesn't publish, or
    publishes too briefly, are skipped by build_panel."""
    rows = []
    for nace, industry, us_ppi, us_ip in SECTORS:
        for kind, what in (("price", "producer prices"), ("output", "output")):
            dataset = EUROSTAT_SECTORS[kind].split("?")[0]
            rows += [Series(f"{kind}_{geo.lower()}_{nace.lower()}", "eurostat_sectors", f"{kind}:{geo}:{nace}",
                            "sectors", "dlog", 2, kind, f"{country}: {industry} {what} (Eurostat {dataset}, {nace})")
                     for geo, country in COUNTRIES.items()]
        for kind, code, what in (("price", us_ppi, "producer prices (BLS PPI"), ("output", us_ip, "output (Fed")):
            if code:
                rows.append(Series(f"{kind}_us_{nace.lower()}", "fred", code, "sectors", "dlog", 1, kind,
                                   f"United States: {industry} {what} {code}, closest NAICS)"))
    return rows


# --- fetching (cached under data/raw/macro/, git-ignored) -----------------------------------

def _get(url: str, path: Path) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as resp:
            path.write_bytes(resp.read())
    return path


def _monthly(s: pd.Series) -> pd.Series:
    return s.dropna().resample("MS").mean()


def fetch_fred(code: str) -> pd.Series:
    path = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}", RAW / f"fred_{code}.csv")
    df = pd.read_csv(path, parse_dates=["observation_date"])
    s = pd.to_numeric(df[code], errors="coerce")
    s.index = df["observation_date"]
    return _monthly(s)


MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
                                      "DEC"], 1)}


def fetch_ons(uri: str) -> pd.Series:
    path = _get(ONS.format(uri), RAW / f"ons_{uri.strip('/').split('/')[-2]}.csv")
    vals = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) != 2:
            continue
        label, value = parts[0].strip('"'), parts[1].strip('"')
        m = re.fullmatch(r"(\d{4}) ([A-Z]{3})", label)
        q = re.fullmatch(r"(\d{4}) Q([1-4])", label)
        if m:
            vals[pd.Timestamp(int(m[1]), MONTHS[m[2]], 1)] = float(value)
        elif q:
            vals[pd.Timestamp(int(q[1]), 3 * int(q[2]), 1)] = float(value)  # quarter's last month
    return pd.Series(vals).sort_index()


def fetch_eurostat(query: str) -> pd.Series:
    dataset, params = query.split("?", 1)
    path = _get(EUROSTAT.format(dataset, params + "&sinceTimePeriod=1998-01"),
                RAW / f"eurostat_{dataset}_{params.split('geo=')[1].split('&')[0]}.json")
    j = json.loads(path.read_text(encoding="utf-8"))
    times = list(j["dimension"]["time"]["category"]["index"])
    vals = {pd.Timestamp(times[int(k)] + "-01"): v for k, v in j["value"].items()}
    if not vals:
        raise ValueError(f"Eurostat returned no values for {query}")
    return pd.Series(vals).sort_index()


def jsonstat_frame(j: dict) -> pd.DataFrame:
    """A Eurostat JSON-stat payload as one column per (geo, nace_r2), one row per month. Values are
    stored flat, keyed by their position in row-major order over the dimensions in j['id']."""
    ids, size = j["id"], j["size"]
    cats = {}
    for d in ids:
        index = j["dimension"][d]["category"]["index"]
        cats[d] = np.array(sorted(index, key=index.get) if isinstance(index, dict) else index)
    pos = np.unravel_index(np.array([int(k) for k in j["value"]], dtype=np.int64), size)
    df = pd.DataFrame({d: cats[d][p] for d, p in zip(ids, pos)})
    df["value"] = np.array(list(j["value"].values()), dtype=float)
    df["time"] = pd.to_datetime(df["time"] + "-01")
    return df.pivot_table(index="time", columns=["geo", "nace_r2"], values="value", aggfunc="first")


_SECTOR_FRAMES: dict[str, pd.DataFrame] = {}


def fetch_eurostat_sectors(code: str) -> pd.Series:
    """One country and industry from the Eurostat sector datasets, which are fetched once for every
    country and SECTORS industry (one request per dataset). Index values <= 0 (an industry that
    stopped, e.g. Lithuanian steel, reported as 0) are missing."""
    kind, geo, nace = code.split(":")
    if kind not in _SECTOR_FRAMES:
        dataset, params = EUROSTAT_SECTORS[kind].split("?")
        params += "".join(f"&nace_r2={s[0]}" for s in SECTORS) + "&sinceTimePeriod=1998-01"
        path = _get(EUROSTAT.format(dataset, params), RAW / f"eurostat_sectors_{dataset}.json")
        _SECTOR_FRAMES[kind] = jsonstat_frame(json.loads(path.read_text(encoding="utf-8")))
    frame = _SECTOR_FRAMES[kind]
    x = frame[(geo, nace)] if (geo, nace) in frame else pd.Series(dtype=float)
    x = x.where(x > 0).dropna()
    if x.empty:
        raise ValueError("not published")
    return x


def fetch_portwatch(code: str) -> pd.Series:
    """Monthly mean of a daily PortWatch field for one chokepoint, paging through the service."""
    port, field = code.split(":")
    path = RAW / f"portwatch_{port}.json"
    if not path.exists():
        rows, offset = [], 0
        while True:
            q = urllib.parse.urlencode({"where": f"portid='{port}'", "outFields": "date,n_tanker,capacity_tanker",
                                        "orderByFields": "date", "resultOffset": offset,
                                        "resultRecordCount": 1000, "f": "json"})
            req = urllib.request.Request(f"{PORTWATCH}?{q}", headers=UA)
            with urllib.request.urlopen(req, timeout=120) as resp:
                page = json.load(resp)
            feats = page.get("features", [])
            rows += [f["attributes"] for f in feats]
            if len(feats) < 1000:
                break
            offset += 1000
            time.sleep(0.5)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows), encoding="utf-8")
    df = pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
    dates = pd.to_datetime(df["date"], unit="ms") if pd.api.types.is_numeric_dtype(df["date"]) \
        else pd.to_datetime(df["date"])
    return _monthly(pd.Series(df[field].astype(float).values, index=dates))


def fetch_eia(code: str) -> pd.Series:
    path = _get(f"https://www.eia.gov/dnav/pet/hist_xls/{code}w.xls", RAW / f"eia_{code}.xls")
    df = pd.read_excel(path, sheet_name="Data 1", skiprows=2)
    return _monthly(pd.Series(df.iloc[:, 1].astype(float).values, index=pd.to_datetime(df["Date"])))


def fetch_ports(code: str) -> pd.Series:
    """Daily tanker exports (tonnes) summed over a group of PortWatch ports, monthly mean."""
    ports = code.split(",")
    path = RAW / f"portwatch_ports_{'_'.join(ports)}.json"
    if not path.exists():
        rows, offset = [], 0
        where = "portid IN (" + ",".join(f"'{p}'" for p in ports) + ")"
        while True:
            q = urllib.parse.urlencode({"where": where, "outFields": "date,portid,export_tanker",
                                        "orderByFields": "date", "resultOffset": offset,
                                        "resultRecordCount": 1000, "f": "json"})
            req = urllib.request.Request(f"{PORTWATCH_PORTS}?{q}", headers=UA)
            with urllib.request.urlopen(req, timeout=120) as resp:
                feats = json.load(resp).get("features", [])
            rows += [f["attributes"] for f in feats]
            if len(feats) < 1000:
                break
            offset += 1000
            time.sleep(0.5)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows), encoding="utf-8")
    df = pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
    df["date"] = pd.to_datetime(df["date"], unit="ms") if pd.api.types.is_numeric_dtype(df["date"]) \
        else pd.to_datetime(df["date"])
    return _monthly(df.groupby("date")["export_tanker"].sum().astype(float))


def fetch_gscpi(code: str) -> pd.Series:
    path = _get(GSCPI_URL, RAW / "gscpi.xlsx")
    df = pd.read_excel(path, sheet_name="GSCPI Monthly Data", header=None).iloc[5:, :2].dropna()
    dates = pd.to_datetime(df[0], format="%d-%b-%Y").dt.to_period("M").dt.to_timestamp()
    return pd.Series(df[1].astype(float).values, index=dates)


def fetch_gpr(code: str) -> pd.Series:
    path = _get(GPR_URL, RAW / "gpr_export.xls")
    df = pd.read_excel(path)
    return pd.Series(df[code].values, index=pd.to_datetime(df["month"])).astype(float)


FETCH = {"fred": fetch_fred, "ons": fetch_ons, "eurostat": fetch_eurostat, "portwatch": fetch_portwatch,
         "gpr": fetch_gpr, "eia": fetch_eia, "ports": fetch_ports, "gscpi": fetch_gscpi,
         "eurostat_sectors": fetch_eurostat_sectors}
URLS = {"fred": "https://fred.stlouisfed.org/series/{}", "ons": "https://www.ons.gov.uk{}",
        "eurostat": "https://ec.europa.eu/eurostat/databrowser/view/{}", "portwatch": "https://portwatch.imf.org",
        "eurostat_sectors": "https://ec.europa.eu/eurostat/databrowser/view/sts_inppd_m (prices), sts_inpr_m (output)",
        "gpr": "https://www.matteoiacoviello.com/gpr.htm", "eia": "https://www.eia.gov/petroleum/data.php",
        "ports": "https://portwatch.imf.org", "gscpi": "https://www.newyorkfed.org/research/policy/gscpi"}


# --- the panel -------------------------------------------------------------------------------

def registry(blocks=BLOCKS) -> list[Series]:
    reg = [s for s in SERIES if s.block in blocks]
    return reg + (industry_series() if "industry" in blocks else []) + (sector_series() if "sectors" in blocks else [])


def build_panel(blocks=BLOCKS, ignore_lags: bool = False):
    """Return (features, levels, provenance).

    features: one row per month; column values are what was public at the end of that month
              (shifted by each series' publication lag), transformed, short gaps forward-filled.
              Blocks with a late start (AIS from 2019) get an `<block>_available` 0/1 column and 0s
              before they start.
    levels:   the untransformed monthly values (log for prices) that targets are computed from.
    ignore_lags=True drops the publication lags; it exists only to measure how much they matter.
    """
    reg = registry(blocks)
    raw, prov = {}, []
    for s in reg:
        try:
            x = FETCH[s.source](s.code)
        except Exception as err:  # a dead source should not take the whole panel down
            prov.append({"series": s, "error": str(err)[:120]})
            continue
        if s.block == "sectors" and (x.dropna().loc[START:].size < SECTOR_MIN_MONTHS
                                     or x.dropna().index.max() < pd.Timestamp(SECTOR_LIVE_FROM)):
            prov.append({"series": s, "error": f"skipped: {x.dropna().loc[START:].size} months from {START[:7]}, "
                                               f"last {x.dropna().index.max():%Y-%m}"})
            continue
        if s.freq == "Q":
            x = x.resample("QS").mean()
            x.index = x.index + pd.offsets.MonthBegin(2)  # value belongs to the quarter's last month
            x = x.resample("MS").ffill()
        raw[s.key] = x
        fetched = min((p.stat().st_mtime for p in RAW.glob("*")), default=time.time())
        prov.append({"series": s, "first": x.dropna().index.min(), "last": x.dropna().index.max(),
                     "fetched": datetime.fromtimestamp(fetched, UTC).date().isoformat()})
    idx = pd.date_range(START, max(v.index.max() for v in raw.values()), freq="MS")
    feats, levels = {}, {}
    for s in reg:
        if s.key not in raw:
            continue
        x = raw[s.key].reindex(idx)
        log = s.transform == "dlog"
        levels[s.key] = np.log(x) if log else x
        # What was known at the end of each month. Short gaps are filled on the level, so a filled
        # month reads as "no change" rather than repeating the last change.
        public = x.shift(0 if ignore_lags else s.lag).ffill(limit=MAX_FILL)
        if s.transform == "dlog":
            feats[f"{s.key}_dlog"] = np.log(public).diff()
        if s.transform in ("diff", "level+diff"):
            feats[f"{s.key}_d"] = public.diff()
        if s.transform in ("level", "level+diff"):
            feats[s.key] = public
        if s.transform == "share":
            feats[f"{s.key}_share"] = public / public.loc[SHARE_BASE[0]:SHARE_BASE[1]].mean()
    F = pd.DataFrame(feats, index=idx)
    for block in MASKED:
        cols = [c for c in F if any(c.startswith(s.key) for s in reg if s.block == block)]
        if cols:
            F[f"{block}_available"] = F[cols].notna().all(axis=1).astype(float)
            F[cols] = F[cols].fillna(0.0)
    return F, pd.DataFrame(levels, index=idx), prov


def main() -> None:
    F, L, prov = build_panel()
    today = datetime.now(UTC).date().isoformat()
    out = [
        "# Macro panel: what goes into the knock-on models",
        "",
        f"_Generated by `experiments/macro_data.py` on {today}. Monthly, {F.index[0]:%Y-%m} to {F.index[-1]:%Y-%m}; "
        f"{F.shape[1]} input columns. Each value is what was public at the end of the month (publication lag in "
        "months below). Nothing here is synthetic._",
        "",
        "| Block | Series | Source id | Role | Lag | Data from | Data to | Fetched |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in prov:
        s = p["series"]
        if "error" in p:
            out.append(f"| {s.block} | {s.name} | `{s.code}` | - | - | **failed: {p['error']}** | | |")
            continue
        role = f"target ({s.target})" if s.target else "input"
        out.append(f"| {s.block} | {s.name} | `{s.code}` | {role} | {s.lag} | {p['first']:%Y-%m} | {p['last']:%Y-%m} | "
                   f"{p['fetched']} |")
    out += ["", f"Sources: " + ", ".join(f"{k}: {v.split('{')[0]}" for k, v in URLS.items()) + ".", ""]
    OUT.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(F.tail(3).T.head(12))


if __name__ == "__main__":
    main()
