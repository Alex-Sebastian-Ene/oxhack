# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scipy>=1.11", "xlrd>=2.0", "openpyxl>=3.1",
#                 "jax>=0.4.30", "numpyro>=0.15"]
# ///
"""Cost of living in an oil supply shock, built up from the basket: bread, meat, dairy, oils and
fats, fruit and vegetables, sugar, electricity, gas, motor fuel, air fares, restaurants, housing
(rent, and owners' equivalent rent in the US), core goods (non-energy industrial goods) and other
services in the US, UK and euro area, each with its own oil and gas pass-through, weighted into a
composite. Other services are each region's services index less the service items modelled on their
own, so nothing is counted twice.

The average historical pass-through fell far short in the 2022 and 2026 supply shocks. This script
measures that miss item by item, then fits one Bayesian model (NUTS) for every item, the rest of
the basket and headline inflation, on their monthly log changes (% of the price level):

    y[s,k] = a[k] + season[k, month] + rho[k] y[s-1,k] + E[s,k] (1 + kappa[k] D[s]) + e[s,k]
    E[s,k] = sum_l B[k,l] x[s-l] + sum_l G[k,l] g_r(k)[s-l]
    e[s,k] = sigma[k] exp(phi[k] v[s] + psi[k] D[s]) z[s,k],   z ~ Student-t(nu[k])

- x: monthly log change of Brent (monthly average); g_r: the region's gas price (Henry Hub for the
  US, the IMF EU gas price for the UK and euro area). Lags 0..12, or 0..2 for motor fuel and fares.
- D: 1 in months of a physical oil supply disruption (2022-03..2022-12, 2026-03..). kappa is the
  extra share of energy-cost pass-through then, pooled across regions for each kind of item; psi
  widens the band. A fit that ends before 2026 learns kappa from 2022 alone.
- v: recent oil volatility (log mean |x| over 3 months), so bands widen in oil turmoil.
- season: month-of-year terms for series that are not seasonally adjusted (UK, euro area).
- The rest of the basket is headline minus the weighted items and other services, with each region's
  latest basket weights, so the composite (weighted items + other services + rest) adds up to headline
  inflation exactly. With housing, core goods and other services modelled it is a 3-8% remainder.
- Bread and cereals also take grain prices (the monthly log change of the mean of IMF wheat and
  maize), lags 0..12: + sum_l F[k,l] grain[s-l]. This is the main model (COL_FOOD=bread, the default,
  runs/col-food-bread). It was adopted after beating the oil-and-gas-only base (COL_FOOD=0,
  runs/col) on the same folds. COL_FOOD=1 gives grain and urea to every food series, restaurants,
  the rest of the basket and headline (+ sum_l U[k,l] urea[s-l]); it scored worse (runs/col-food).

Forecasts simulate every series month by month. The noise is a bootstrap of the fitted
standardised residual vectors, so items keep the correlations they had and the composite band is
not too narrow. Brent paths come from the daily GARCH-CGMY Lévy model of experiments/levy_fourier.py
(the yearly refits stored in runs/levy/rolling-*.json, each trained only on earlier years),
averaged into months; daily GARCH-Student-t and a monthly GARCH-t are scored against it.

    uv run experiments/cost_of_living.py events      # item-level misses in 2022 and 2026, fuel ratios
    uv run experiments/cost_of_living.py fit fold-3  # one fit: fold-0..7, event-2022, event-2026, final
    uv run experiments/cost_of_living.py all         # every fit, in sequence
    uv run experiments/cost_of_living.py report      # notes/cost-of-living.md and CSVs for the UI
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CHAINS = int(os.environ.get("COL_CHAINS", 2))
os.environ.setdefault("XLA_FLAGS", f"--xla_force_host_platform_device_count={CHAINS}")

import jax  # noqa: E402
import jax.numpy as jnp  # noqa: E402
import numpy as np  # noqa: E402
import numpyro  # noqa: E402
import numpyro.distributions as dist  # noqa: E402
import pandas as pd  # noqa: E402
from numpyro.infer import MCMC, NUTS  # noqa: E402
from scipy import optimize, stats  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import levy_fourier as lf  # noqa: E402
import macro_data as md  # noqa: E402
import oil_chain as oc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# COL_FOOD: bread = the main model, oil and gas for every series plus grain prices for bread and
# cereals; 0 = oil and gas only (the base it was tested against); 1 = grain and urea for every food
# series (tested, worse). Each version writes its own runs folder, so all are scored on the same folds.
FOOD_MODE = os.environ.get("COL_FOOD", "bread")
FOOD = FOOD_MODE != "0"
RUNS_BASE, RUNS_FOOD, RUNS_BREAD = ROOT / "runs" / "col", ROOT / "runs" / "col-food", ROOT / "runs" / "col-food-bread"
RUNS_MAIN = RUNS_BREAD
RUNS = {"0": RUNS_BASE, "1": RUNS_FOOD, "bread": RUNS_BREAD}[FOOD_MODE]
NOTES, LEVY_RUNS = ROOT / "notes", ROOT / "runs" / "levy"
START = "2000-01-01"
LAGS = 13  # oil and gas lags 0..12
H = 12  # months ahead
HS = (1, 3, 6, 12)  # horizons scored
WARMUP = int(os.environ.get("COL_WARMUP", 500))
SAMPLES = int(os.environ.get("COL_SAMPLES", 500))  # per chain
DRAWS = 400  # posterior draws that go into the simulations
# COL_DRAWS: keys (comma-separated) whose 1-3 month Lévy forecasts each fold also saves, every draw
# and origin, to fold-<j>-draws.npz, for rescoring against first-published CPI and nowcasts
SAVE_KEYS = [k for k in os.environ.get("COL_DRAWS", "").split(",") if k]
VOL_FLOOR, NU_MIN, SIGMA_FLOOR = 0.05, 2.5, 0.05
SHOCK = np.log(1.10)
DAYS = 21  # trading days per simulated month
QUICK = False


@dataclass(frozen=True)
class Item:
    key: str
    region: str  # us | uk | ea
    kind: str  # one of KINDS
    source: str  # fred | ons | derived
    code: str
    name: str
    weight: str | None  # ONS weight CDID, Eurostat COICOP, or None (US: US_WEIGHTS)
    nsa: bool  # not seasonally adjusted: month-of-year terms are fitted
    lags: int  # oil and gas lags, months
    transform: str = "dlog"  # dlog: % change of the level (x100); diff: change in percentage points
    basket: bool = True  # part of its region's cost-of-living composite


KINDS = ("bread", "meat", "dairy", "oils_fats", "fruit_veg", "sugar", "electricity", "gas", "fuel", "air",
         "restaurants", "housing", "core_goods", "services", "rest", "all", "ind_fuel", "ind_transport",
         "ind_materials", "unemployment", "rate")
KIND_NAMES = {"bread": "Bread and cereals", "meat": "Meat", "dairy": "Dairy", "oils_fats": "Oils and fats",
              "fruit_veg": "Fruit and vegetables", "sugar": "Sugar and sweets", "electricity": "Electricity",
              "gas": "Household gas", "fuel": "Motor fuel", "air": "Air fares", "restaurants": "Restaurants",
              "housing": "Housing (rent, and owners' equivalent rent in the US)",
              "core_goods": "Core goods (non-energy industrial goods)", "services": "Other services",
              "rest": "Rest of the basket", "all": "Headline (direct)", "ind_fuel": "Industry fuel (US)",
              "ind_transport": "Freight and air transport (US)", "ind_materials": "Materials (US)",
              "unemployment": "Unemployment", "rate": "Policy rate"}
ONS_URI = "/economy/inflationandpriceindices/timeseries/{}/mm23"


def _us(key, kind, code, name, lags=12):
    return Item(f"us_{key}", "us", kind, "fred", code, f"US CPI {name} (BLS)", None, False, lags)


def _uk(key, kind, cdid, wcdid, name, lags=12):
    return Item(f"uk_{key}", "uk", kind, "ons", ONS_URI.format(cdid), f"UK CPI {name} (ONS {cdid.upper()})", wcdid,
                True, lags)


def _ea(key, kind, coicop, name, lags=12):
    return Item(f"ea_{key}", "ea", kind, "fred", f"{coicop}EZ19M086NEST", f"Euro-area HICP {name} (Eurostat via FRED)",
                coicop, True, lags)


ITEMS = [
    _us("bread", "bread", "CUSR0000SAF111", "cereals and bakery products"),
    _us("meat", "meat", "CUSR0000SAF112", "meats, poultry, fish and eggs"),
    _us("dairy", "dairy", "CUSR0000SEFJ", "dairy and related products"),
    _us("oils_fats", "oils_fats", "CUSR0000SEFS", "fats and oils"),
    _us("fruit_veg", "fruit_veg", "CUSR0000SAF113", "fruits and vegetables"),
    _us("sugar", "sugar", "CUSR0000SEFR", "sugar and sweets"),
    _us("electricity", "electricity", "CUSR0000SEHF01", "electricity"),
    _us("gas", "gas", "CUSR0000SEHF02", "utility (piped) gas service"),
    _us("fuel", "fuel", "CUSR0000SETB01", "gasoline, all types", lags=2),
    _us("air", "air", "CUSR0000SETG01", "airline fares", lags=2),
    _us("restaurants", "restaurants", "CUSR0000SEFV", "food away from home"),
    _uk("bread", "bread", "d7d5", "cjwb", "01.1.1 bread and cereals"),
    _uk("meat", "meat", "d7d6", "cjwc", "01.1.2 meat"),
    _uk("dairy", "dairy", "d7d8", "cjwe", "01.1.4 milk, cheese and eggs"),
    _uk("oils_fats", "oils_fats", "d7d9", "cjwf", "01.1.5 oils and fats"),
    _uk("fruit", "fruit_veg", "d7da", "cjwg", "01.1.6 fruit"),
    _uk("vegetables", "fruit_veg", "d7db", "cjwh", "01.1.7 vegetables"),
    _uk("sugar", "sugar", "d7dc", "cjwi", "01.1.8 sugar, jam, chocolate and confectionery"),
    _uk("electricity", "electricity", "d7dt", "cjxa", "04.5.1 electricity"),
    _uk("gas", "gas", "d7du", "cjxb", "04.5.2 gas"),
    _uk("fuel", "fuel", "d7ec", "cjxr", "07.2.2 fuels and lubricants", lags=2),
    _uk("air", "air", "d7eh", "cjxw", "07.3.3 passenger transport by air", lags=2),
    _uk("restaurants", "restaurants", "d7ew", "cjyl", "11.1.1 restaurants and cafes"),
    _ea("bread", "bread", "CP0111", "bread and cereals"),
    _ea("meat", "meat", "CP0112", "meat"),
    _ea("dairy", "dairy", "CP0114", "milk, cheese and eggs"),
    _ea("oils_fats", "oils_fats", "CP0115", "oils and fats"),
    _ea("fruit", "fruit_veg", "CP0116", "fruit"),
    _ea("vegetables", "fruit_veg", "CP0117", "vegetables"),
    _ea("sugar", "sugar", "CP0118", "sugar, jam, honey, chocolate and confectionery"),
    _ea("electricity", "electricity", "CP0451", "electricity"),
    _ea("gas", "gas", "CP0452", "gas"),
    _ea("fuel", "fuel", "CP0722", "fuels and lubricants for personal transport", lags=2),
    _ea("air", "air", "CP0733", "passenger transport by air", lags=2),
    _ea("restaurants", "restaurants", "CP1111", "restaurants, cafés and the like"),
    # Housing and core goods. UK CPI and the HICP leave out owner-occupiers' housing costs (the UK
    # puts them in CPIH), so their housing is actual rents only; the US adds owners' equivalent rent.
    _us("rent", "housing", "CUSR0000SEHA", "rent of primary residence"),
    _us("oer", "housing", "CUSR0000SEHC", "owners' equivalent rent of residences"),
    _us("core_goods", "core_goods", "CUSR0000SACL1E", "commodities less food and energy commodities"),
    _uk("rent", "housing", "d7ce", "cjvc", "04.1 actual rents for housing"),
    _uk("core_goods", "core_goods", "dk9j", "a9er", "non-energy industrial goods"),
    Item("ea_rent", "ea", "housing", "fred", "CP0410EZ19M086NEST", "Euro-area HICP actual rentals for housing "
         "(Eurostat via FRED)", "CP041", True, 12),
    Item("ea_core_goods", "ea", "core_goods", "eurostat18", "EA19:IGD_NNRG", "Euro-area HICP non-energy industrial "
         "goods (Eurostat prc_hicp_minr, EA19)", "IGD_NNRG", True, 12),
]
# Other services: each region's services index less the service items modelled on their own,
# derived like the rest of the basket, so nothing is counted twice. US "services less energy
# services" holds rent, OER and air fares (food away from home is food); UK CPI and HICP services
# hold rents, air fares and restaurants.
SERVICES = {"us": (Item("us_services_all", "us", "agg", "fred", "CUSR0000SASLE", "US CPI services less energy "
                        "services (BLS)", None, False, 12), ("us_rent", "us_oer", "us_air")),
            "uk": (Item("uk_services_all", "uk", "agg", "ons", ONS_URI.format("d7f5"), "UK CPI services (ONS D7F5)",
                        "icvi", True, 12), ("uk_rent", "uk_air", "uk_restaurants")),
            "ea": (Item("ea_services_all", "ea", "agg", "eurostat18", "EA19:SERV", "Euro-area HICP services (Eurostat "
                        "prc_hicp_minr, EA19)", "SERV", True, 12), ("ea_rent", "ea_air", "ea_restaurants"))}
HEADLINE = {"us": Item("us_all", "us", "all", "fred", "CPIAUCSL", "US CPI, all items (BLS)", None, False, 12),
            "uk": Item("uk_all", "uk", "all", "ons", ONS_URI.format("d7bt"), "UK CPI, all items (ONS D7BT)", None, True, 12),
            "ea": Item("ea_all", "ea", "all", "fred", "CP0000EZ19M086NEST", "Euro-area HICP, all items (Eurostat via FRED)",
                       None, True, 12)}
REGIONS = {"us": "US", "uk": "UK", "ea": "Euro area"}


def _ind(key, kind, code, name, lags):
    return Item(f"ind_{key}", "us", kind, "fred", code, name, None, True, lags, basket=False)


# Outside the basket: the chain's other metrics, so each gets its own fitted supply-disruption
# multiplier. US industry costs (the industry lane's series), unemployment and policy rates.
OTHER = [
    _ind("diesel", "ind_fuel", "GASDESW", "US retail diesel (EIA)", 2),
    _ind("jet", "ind_fuel", "DJFUELUSGULF", "US Gulf Coast jet fuel (EIA)", 2),
    _ind("refineries", "ind_fuel", "PCU324110324110", "US PPI petroleum refineries (BLS)", 2),
    _ind("truckload", "ind_transport", "PCU484121484121", "US PPI long-distance truckload (BLS)", 2),
    _ind("trucking", "ind_transport", "PCU4841248412", "US PPI long-distance trucking (BLS)", 2),
    _ind("deepsea", "ind_transport", "PCU483111483111", "US PPI deep-sea freight (BLS)", 2),
    _ind("airfreight", "ind_transport", "PCU481112481112", "US PPI scheduled air freight (BLS)", 2),
    _ind("airfares", "ind_transport", "PCU481111481111", "US PPI scheduled passenger air (BLS)", 2),
    _ind("resin", "ind_materials", "PCU325211325211", "US PPI plastics resin (BLS)", 12),
    _ind("film", "ind_materials", "PCU3261132611", "US PPI plastic film and bags (BLS)", 12),
    _ind("bottles", "ind_materials", "PCU326160326160", "US PPI plastic bottles (BLS)", 12),
    _ind("paper", "ind_materials", "WPU0915", "US PPI converted paper and paperboard (BLS)", 12),
    _ind("fertiliser", "ind_materials", "PCU325311325311", "US PPI nitrogen fertiliser (BLS)", 12),
    Item("us_unemp", "us", "unemployment", "fred", "UNRATE", "US unemployment rate (BLS)", None, False, 12, "diff", False),
    Item("uk_unemp", "uk", "unemployment", "fred", "LRHUTTTTGBM156S", "UK unemployment rate (OECD via FRED)", None,
         False, 12, "diff", False),
    Item("ea_unemp", "ea", "unemployment", "eurostat", "une_rt_m?geo=EA21&s_adj=SA&age=TOTAL&unit=PC_ACT&sex=T&freq=M",
         "Euro-area unemployment rate, EA21 (Eurostat)", None, False, 12, "diff", False),
    Item("us_rate", "us", "rate", "fred", "FEDFUNDS", "Effective fed funds rate (Fed)", None, False, 12, "diff", False),
    Item("uk_rate", "uk", "rate", "fred", "IUDSOIA", "SONIA overnight rate (Bank of England via FRED)", None, False, 12,
         "diff", False),
    Item("ea_rate", "ea", "rate", "fred", "ECBDFR", "ECB deposit facility rate (ECB via FRED)", None, False, 12, "diff",
         False),
]
SERVICE_ITEMS = [Item(f"{r}_services", r, "services", "derived", f"{SERVICES[r][0].key} minus "
                      + ", ".join(SERVICES[r][1]), f"{REGIONS[r]} other services ({SERVICES[r][0].name.split(' (')[0]} "
                      "less the service items above)", None, SERVICES[r][0].nsa, 12) for r in REGIONS]
SERIES = (ITEMS + SERVICE_ITEMS + [Item(f"{r}_rest", r, "rest", "derived", f"{r}_all minus weighted items",
                                         f"{REGIONS[r]} rest of basket (remainder: other food, other fuels, "
                                         "aggregation residual)", None, HEADLINE[r].nsa, 12) for r in REGIONS]
          + list(HEADLINE.values()) + OTHER)
# Policy rates move in steps and sit still for years, so their error scale needs a wider floor (as
# in experiments/macro_bayes.py), in units of each series' training sd.
SIGMA_FLOORS = {"rate": 0.2}
# US basket weights: BLS relative importance, CPI-U, December 2025 (% of all items), read from
# https://www.bls.gov/cpi/tables/relative-importance/2025.htm (BLS refuses scripted downloads): the
# food, energy, fares and restaurant items on 2026-10-24, housing, core goods and services on
# 2026-10-25. UK: ONS CPI weights (parts per 1000). Euro area: Eurostat prc_hicp_inw (per 1000).
US_WEIGHTS = {"us_bread": 1.035, "us_meat": 1.995, "us_dairy": 0.758, "us_oils_fats": 0.231, "us_fruit_veg": 1.269,
              "us_sugar": 0.328, "us_electricity": 2.489, "us_gas": 0.773, "us_fuel": 2.895, "us_air": 0.881,
              "us_restaurants": 5.373, "us_rent": 7.840, "us_oer": 26.204, "us_core_goods": 19.176,
              "us_services_all": 60.744}
US_WEIGHTS_SOURCE = "BLS relative importance, CPI-U, December 2025 (collected 2026-10-24 and 2026-10-25)"
# Driver keys must not clash with series keys (load() puts both in one table).
DRIVERS = {"brent": ("fred", "DCOILBRENTEU", "Brent spot, $/bbl (EIA via FRED)"),
           "henry_hub": ("fred", "MHHNGSP", "Henry Hub natural gas spot, monthly (EIA via FRED)"),
           "eu_gas": ("fred", "PNGASEUUSDM", "EU natural gas price (IMF via FRED)"),
           "wheat": ("fred", "PWHEAMTUSDM", "Global price of wheat, $/t (IMF via FRED)"),
           "maize": ("fred", "PMAIZMTUSDM", "Global price of maize, $/t (IMF via FRED)"),
           "urea": ("pinksheet", "Urea", "Urea, $/t (World Bank Pink Sheet)")}
# Series whose prices grain and fertiliser can reach (food, restaurants, and the aggregates).
FOOD_KINDS = ("bread", "meat", "dairy", "oils_fats", "fruit_veg", "sugar", "restaurants", "rest", "all")
DRIVEN_KINDS = ("bread",) if FOOD_MODE == "bread" else FOOD_KINDS  # the series that get the food drivers
# The World Bank moves this file with every monthly update; the cached copy is what the fits used.
PINK_URL = ("https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/"
            "CMO-Historical-Data-Monthly.xlsx")
PINK_FILE = "worldbank_CMO-Historical-Data-Monthly.xlsx"
SUPPLY = [("2022-03-01", "2022-12-01", "Russia's invasion of Ukraine and the embargoes"),
          ("2026-03-01", "2026-12-01", "Hormuz closure")]
CLOSURE = ("2026-03-01", "2026-09-01")  # the closure months used as the scenario template
EVENTS = [("2022 Russia", "2022-02-01", "2022-12-01"), ("2026 Hormuz", "2026-02-01", "2026-09-01")]


# --- data ------------------------------------------------------------------------------------

def fetched(it: Item) -> str:
    if it.source == "fred":
        name = f"fred_{it.code}.csv"
    elif it.source == "pinksheet":
        name = PINK_FILE
    elif it.source == "eurostat18":
        name = "eurostat_prc_hicp_minr_{}_{}.json".format(*it.code.split(":"))
    elif it.source == "eurostat":
        name = f"eurostat_{it.code.split('?')[0]}_{it.code.split('geo=')[1].split('&')[0]}.json"
    else:
        name = f"ons_{it.code.strip('/').split('/')[-2]}.csv"
    p = md.RAW / name
    return datetime.fromtimestamp(p.stat().st_mtime, UTC).date().isoformat() if p.exists() else "-"


def fetch_pinksheet(column: str) -> pd.Series:
    """A monthly price from the World Bank Pink Sheet ("Monthly Prices"; names on the 5th row)."""
    path = md._get(PINK_URL, md.RAW / PINK_FILE)
    df = pd.read_excel(path, "Monthly Prices", header=None, skiprows=4)
    col = [str(c).strip() for c in df.iloc[0]].index(column)
    rows = df.iloc[2:]
    s = pd.to_numeric(rows[col], errors="coerce")
    s.index = pd.to_datetime(rows[0].astype(str).str.replace("M", "-") + "-01", errors="coerce")
    return s[s.index.notna()].dropna()


def fetch_eurostat18(code: str) -> pd.Series:
    """A monthly HICP index (2015 = 100) from Eurostat's COICOP 2018 dataset prc_hicp_minr, "GEO:COICOP".
    The older prc_hicp_midx stops at 2025-12; the special aggregates (services, non-energy industrial
    goods) are not on FRED."""
    geo, coicop = code.split(":")
    path = md._get(md.EUROSTAT.format("prc_hicp_minr", f"geo={geo}&coicop18={coicop}&unit=I15&sinceTimePeriod=1996-01"),
                   md.RAW / f"eurostat_prc_hicp_minr_{geo}_{coicop}.json")
    j = json.loads(path.read_text(encoding="utf-8"))
    times = list(j["dimension"]["time"]["category"]["index"])
    return pd.Series({pd.Timestamp(times[int(k)] + "-01"): v for k, v in j["value"].items()}).sort_index()


FETCH = md.FETCH | {"pinksheet": fetch_pinksheet, "eurostat18": fetch_eurostat18}


def ons_annual(cdid: str) -> pd.Series:
    uri = ONS_URI.format(cdid)
    path = md._get(md.ONS.format(uri), md.RAW / f"ons_{cdid}.csv")
    vals = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) == 2 and re.fullmatch(r"\d{4}", parts[0].strip('"')):
            vals[int(parts[0].strip('"'))] = float(parts[1].strip('"'))
    return pd.Series(vals).sort_index()


def eurostat_weights(coicops: list[str]) -> dict[str, tuple[int, float]]:
    q = "&".join(f"coicop={c}" for c in coicops)
    # The cache file is named after the code list, so adding items fetches a fresh copy.
    tag = "items" if len(coicops) == 12 else f"items{len(coicops)}"
    path = md._get(md.EUROSTAT.format("prc_hicp_inw", f"geo=EA&{q}&sinceTimePeriod=2018"),
                   md.RAW / f"eurostat_prc_hicp_inw_EA_{tag}.json")
    j = json.loads(path.read_text(encoding="utf-8"))
    cats = list(j["dimension"]["coicop"]["category"]["index"])
    times = list(j["dimension"]["time"]["category"]["index"])
    out = {}
    for c in coicops:
        ci = cats.index(c)
        vals = [(int(times[t]), j["value"].get(str(ci * len(times) + t))) for t in range(len(times))]
        year, w = max((y, v) for y, v in vals if v is not None)
        out[c] = (year, float(w))
    return out


def weights() -> dict:
    """Latest basket weight of every item, as a share of its region's headline, and the rest."""
    w, year = {}, {}
    for k, v in US_WEIGHTS.items():
        w[k], year[k] = v / 100, 2025
    aggs = [SERVICES[r][0] for r in REGIONS]
    for it in ITEMS + aggs:
        if it.region == "uk":
            s = ons_annual(it.weight)
            w[it.key], year[it.key] = float(s.iloc[-1]) / 1000, int(s.index[-1])
    ea = eurostat_weights([it.weight for it in ITEMS + aggs if it.region == "ea"])
    for it in ITEMS + aggs:
        if it.region == "ea":
            year[it.key], w[it.key] = ea[it.weight][0], ea[it.weight][1] / 1000
    for r in REGIONS:  # other services: the services total less the service items modelled on their own
        agg, parts = SERVICES[r]
        w[f"{r}_services"], year[f"{r}_services"] = w[agg.key] - sum(w[k] for k in parts), year[agg.key]
    comp = {it.key for it in ITEMS} | {it.key for it in SERVICE_ITEMS}
    for r in REGIONS:
        w[f"{r}_rest"] = 1 - sum(v for k, v in w.items() if k in comp and k.startswith(f"{r}_"))
    return {"w": w, "year": year}


def derive_rest(ch: pd.DataFrame, w: dict) -> pd.DataFrame:
    """Add each region's other services (the services total less the service items modelled on their
    own) and rest of the basket (headline minus every weighted item and other services), each over its
    own weight, so that the weighted items, other services and the rest give headline exactly."""
    for r in REGIONS:
        agg, parts = SERVICES[r]
        ch[f"{r}_services"] = (w[agg.key] * ch[agg.key] - sum(w[k] * ch[k] for k in parts)) / w[f"{r}_services"]
        items = [it.key for it in ITEMS if it.region == r] + [f"{r}_services"]
        ch[f"{r}_rest"] = (ch[f"{r}_all"] - sum(w[k] * ch[k] for k in items)) / w[f"{r}_rest"]
    return ch


def load() -> dict:
    """Monthly log changes (x100) of every series from START to the last month all items share."""
    raw = {k: FETCH[src](code) for k, (src, code, _) in DRIVERS.items()}
    basket_inputs = ITEMS + [SERVICES[r][0] for r in REGIONS] + list(HEADLINE.values())
    raw |= {it.key: FETCH[it.source](it.code) for it in basket_inputs + OTHER}
    # The panel ends with the basket's last month; the other metrics are NaN after their own last month.
    end = min(raw[it.key].dropna().index.max() for it in basket_inputs)
    idx = pd.date_range(START, end, freq="MS")
    diff_keys = {s.key for s in OTHER if s.transform == "diff"}
    lv = pd.DataFrame({k: np.log(v.reindex(idx)) for k, v in raw.items() if k not in diff_keys})
    wt = weights()
    ch = derive_rest(lv.diff() * 100.0, wt["w"])
    for k in diff_keys:  # unemployment and rates: changes in percentage points
        ch[k] = raw[k].reindex(idx).diff()
    keys = [s.key for s in SERIES]
    D = np.zeros(len(idx))
    for a, b, _ in SUPPLY:
        D[(idx >= a) & (idx <= b)] = 1.0
    prov = {k: (f"{v.dropna().index.min():%Y-%m}", f"{v.dropna().index.max():%Y-%m}") for k, v in raw.items()}
    return {"months": idx, "keys": keys, "y": ch[keys].values, "x": ch["brent"].values / 100,
            "g_us": ch["henry_hub"].values / 100, "g_eu": ch["eu_gas"].values / 100,
            "g_grain": (ch["wheat"] + ch["maize"]).values / 200, "g_urea": ch["urea"].values / 100, "D": D, "prov": prov,
            "weights": wt, "brent_level": np.exp(lv["brent"].values)}


def lagmat(z: np.ndarray, lags: int = LAGS - 1, fill: float = np.nan) -> np.ndarray:
    """[n, lags+1]: column l is z shifted down by l months."""
    return np.column_stack([np.concatenate([np.full(l, fill), z[:len(z) - l]]) for l in range(lags + 1)])


def composite_index(region: str) -> tuple[np.ndarray, np.ndarray]:
    """Indices into SERIES of a region's items and rest, for the composite."""
    idx = [i for i, s in enumerate(SERIES) if s.region == region and s.basket and s.kind != "all"]
    return np.array(idx), np.array([SERIES[i].key for i in idx])


# --- the average link and the event misses ---------------------------------------------------

def ols_design(data: dict, k: int, gas: bool = True) -> np.ndarray:
    s = SERIES[k]
    cols = [np.ones(len(data["x"])), lagmat(data["x"], s.lags)]
    if gas:
        cols.append(lagmat(data["g_us" if s.region == "us" else "g_eu"], s.lags))
    if s.nsa:
        m = data["months"].month.values
        cols.append(np.column_stack([(m == j).astype(float) for j in range(2, 13)]))
    return np.column_stack(cols)


def ols_fit(data: dict, k: int, last: int, gas: bool = True):
    """The average link for series k on months up to `last`: OLS on oil (and gas) lags, month terms."""
    X, y = ols_design(data, k, gas), data["y"][:, k]
    ok = np.isfinite(y) & np.isfinite(X).all(1)
    ok[last + 1:] = False
    b = np.linalg.lstsq(X[ok], y[ok], rcond=None)[0]
    return b, float((y[ok] - X[ok] @ b).std(ddof=X.shape[1])), X


def event_table(data: dict) -> list[dict]:
    """Each event: actual cumulative change against the average link fitted up to the month before,
    given the oil (and gas) that happened. Composite rows weight items and rest."""
    rows, months, w = [], data["months"], data["weights"]["w"]
    for label, a, b in EVENTS:
        base, end = months.get_loc(pd.Timestamp(a)), months.get_loc(pd.Timestamp(b))
        res = {}
        for k, s in enumerate(SERIES):
            y = data["y"][base + 1:end + 1, k]
            if not np.isfinite(y).all():
                continue
            pred = {}
            for gas in (False, True):
                bb, _, X = ols_fit(data, k, base, gas)
                pred[gas] = float(np.sum(X[base + 1:end + 1] @ bb))
            res[s.key] = {"actual": float(np.sum(y)), "oil_only": pred[False], "oil_gas": pred[True]}
        for r in REGIONS:
            _, keys = composite_index(r)
            if all(k in res for k in keys):
                res[f"{r}_composite"] = {f: sum(w[k] * res[k][f] for k in keys) for f in ("actual", "oil_only", "oil_gas")}
        for key, v in res.items():
            rows.append({"event": label, "key": key, "base": f"{months[base]:%Y-%m}", "end": f"{months[end]:%Y-%m}",
                         "brent": 100 * float(np.sum(data["x"][base + 1:end + 1])),
                         "weight": w.get(key, 1.0 if key.endswith(("_all", "_composite")) else None)} | v)
    return rows


FUEL_EVENTS = [("1990 Kuwait", "1990-07", "1990-10"), ("2019 Abqaiq", "2019-08", "2019-09"),
               ("2022 Russia, 1 month", "2022-02", "2022-03"), ("2022 Russia, to diesel peak", "2022-02", "2022-06"),
               ("2026 Hormuz, 1 month", "2026-02", "2026-03"), ("2026 Hormuz, to Sep", "2026-02", "2026-09")]


def fuel_ratios() -> list[dict]:
    """US retail diesel and Gulf Coast jet fuel against Brent in supply events, from monthly averages."""
    brent, diesel, jet = (md.FETCH["fred"](c) for c in ("DCOILBRENTEU", "GASDESW", "DJFUELUSGULF"))
    out = []
    for label, a, b in FUEL_EVENTS:
        a, b = pd.Timestamp(a + "-01"), pd.Timestamp(b + "-01")
        lb = np.log(brent[b] / brent[a])
        row = {"event": label, "from": f"{a:%Y-%m}", "to": f"{b:%Y-%m}", "brent_pct": 100 * (brent[b] / brent[a] - 1),
               "brent_from": float(brent[a]), "brent_to": float(brent[b])}
        for name, s in (("diesel", diesel), ("jet", jet)):
            ok = a in s.index and b in s.index and np.isfinite(s.get(a, np.nan)) and np.isfinite(s.get(b, np.nan))
            row[f"{name}_pct"] = float(100 * (s[b] / s[a] - 1)) if ok else None
            row[f"{name}_per10"] = float(100 * np.log(s[b] / s[a]) / lb * SHOCK) if ok else None
        out.append(row)
    return out


def fuel_average_links() -> dict:
    """The average link for diesel and jet fuel (oil lags 0..2, 2000 onwards), for comparison."""
    brent = np.log(md.FETCH["fred"]("DCOILBRENTEU"))
    out = {}
    for name, code in (("diesel", "GASDESW"), ("jet", "DJFUELUSGULF")):
        p = np.log(md.FETCH["fred"](code))
        idx = pd.date_range(START, min(p.index.max(), brent.index.max()), freq="MS")
        y, x = p.reindex(idx).diff().values * 100, brent.reindex(idx).diff().values
        X = np.column_stack([np.ones(len(x)), lagmat(x, 2)])
        ok = np.isfinite(y) & np.isfinite(X).all(1)
        b, cov = oc.ols_hac(y[ok], X[ok], 6)
        out[name] = {"per10": float(b[1:].sum() * SHOCK), "se": float(np.sqrt(cov[1:, 1:].sum()) * SHOCK)}
    return out


# --- the Bayesian model ----------------------------------------------------------------------

ENERGY = ("x", "g_us", "g_eu")  # Brent and the two gas prices: the energy-cost pass-through
FOODIN = {"0": (), "1": ("g_grain", "g_urea"), "bread": ("g_grain",)}[FOOD_MODE]  # grains (wheat, maize), urea
CHANNELS = ENERGY + FOODIN
GROUPS = {"oil": ("x",), "gas": ("g_us", "g_eu"), "grain": ("g_grain",), "urea": ("g_urea",)}


class Stats:
    """Standardisation from training months only."""

    def __init__(self, data: dict, last: int) -> None:
        sl = slice(1, last + 1)
        self.sd = {c: float(np.nanstd(data[c][sl])) for c in CHANNELS}
        self.xs = self.sd["x"]
        lv = log_vol(np.nan_to_num(data["x"]) / self.xs)[LAGS:last + 1]
        self.vm, self.vs = float(lv.mean()), float(lv.std())
        y = data["y"][LAGS:last + 1]
        self.ym, self.ys = np.nanmean(y, 0), np.nanstd(y, 0)


def log_vol(z: np.ndarray) -> np.ndarray:
    a = np.abs(z)
    return np.log((a + np.r_[0, a[:-1]] + np.r_[0, 0, a[:-2]]) / 3 + VOL_FLOOR)


def standardised(data: dict, st: Stats) -> dict:
    z = {c: np.nan_to_num(data[c]) / st.sd[c] for c in CHANNELS}
    z["v"] = (log_vol(z["x"]) - st.vm) / st.vs
    z["y"] = (data["y"] - st.ym) / st.ys
    return z


def series_arrays() -> dict:
    lags = np.array([s.lags for s in SERIES])
    return {"lagmask": (np.arange(LAGS)[None, :] <= lags[:, None]).astype(float),
            "gsel": np.array([s.region == "us" for s in SERIES]),
            "nsa": np.array([s.nsa for s in SERIES], float),
            "kind": np.array([KINDS.index(s.kind) for s in SERIES]),
            "fmask": np.array([s.kind in DRIVEN_KINDS for s in SERIES], float),
            "floor": np.array([SIGMA_FLOORS.get(s.kind, SIGMA_FLOOR) for s in SERIES])}


def model(Zx, Zus, Zeu, mon, D, v, yprev, y, lagmask, gsel, nsa, kind, fmask, floor, Zgr=None, Zur=None):
    K = y.shape[1]
    B = numpyro.deterministic("Bm", numpyro.sample("B", dist.Normal(0, 0.3).expand([K, LAGS]).to_event(2)) * lagmask)
    G = numpyro.deterministic("Gm", numpyro.sample("G", dist.Normal(0, 0.3).expand([K, LAGS]).to_event(2)) * lagmask)
    a = numpyro.sample("a", dist.Normal(0, 1).expand([K]).to_event(1))
    s_raw = numpyro.sample("s_raw", dist.Normal(0, 1).expand([K, 11]).to_event(2))
    S = numpyro.deterministic("S", jnp.concatenate([jnp.zeros((K, 1)), s_raw], 1) * nsa[:, None])
    rho = numpyro.deterministic("rho", 0.95 * jnp.tanh(numpyro.sample("rho_raw", dist.Normal(0, 0.5).expand([K]).to_event(1))))
    mu_k = numpyro.sample("mu_kappa", dist.Normal(0, 1).expand([len(KINDS)]).to_event(1))
    tau_k = numpyro.sample("tau_kappa", dist.HalfNormal(0.5))
    kz = numpyro.sample("kz", dist.Normal(0, 1).expand([K]).to_event(1))
    kappa = numpyro.deterministic("kappa", mu_k[kind] + tau_k * kz)
    phi = numpyro.sample("phi", dist.Normal(0, 0.5).expand([K]).to_event(1))
    psi = numpyro.sample("psi", dist.Normal(0, 0.5).expand([K]).to_event(1))
    sigma = numpyro.deterministic("sigma", floor + numpyro.sample("sigma_raw", dist.HalfNormal(1).expand([K]).to_event(1)))
    nu = numpyro.deterministic("nu", NU_MIN + numpyro.sample("nu_m", dist.Gamma(2, 0.1).expand([K]).to_event(1)))
    energy = Zx @ B.T + jnp.where(gsel[None, :], Zus @ G.T, Zeu @ G.T)
    m = a + S[:, mon].T + rho * jnp.nan_to_num(yprev) + energy * (1 + kappa * D[:, None])
    food = lagmask * fmask[:, None]  # grain and urea pass-through, for the food-driven series only
    if Zgr is not None:
        Fg = numpyro.deterministic("Fg", numpyro.sample("Fgr", dist.Normal(0, 0.3).expand([K, LAGS]).to_event(2)) * food)
        m = m + Zgr @ Fg.T
    if Zur is not None:
        Fu = numpyro.deterministic("Fu", numpyro.sample("Fur", dist.Normal(0, 0.3).expand([K, LAGS]).to_event(2)) * food)
        m = m + Zur @ Fu.T
    scale = sigma * jnp.exp(phi * v[:, None] + psi * D[:, None])
    ok = jnp.isfinite(y) & jnp.isfinite(yprev)
    with numpyro.handlers.mask(mask=ok):
        numpyro.sample("y", dist.StudentT(nu, m, scale), obs=jnp.nan_to_num(y))


KEEP = ("Bm", "Gm", "Fg", "Fu", "a", "S", "rho", "kappa", "mu_kappa", "phi", "psi", "sigma", "nu")


def fit_inputs(data: dict, st: Stats, last: int) -> dict:
    z = standardised(data, st)
    rows = np.arange(LAGS, last + 1)
    inp = {"Zx": lagmat(z["x"], fill=0.0)[rows], "Zus": lagmat(z["g_us"], fill=0.0)[rows],
           "Zeu": lagmat(z["g_eu"], fill=0.0)[rows], "mon": data["months"].month.values[rows] - 1,
           "D": data["D"][rows], "v": z["v"][rows], "yprev": z["y"][rows - 1], "y": z["y"][rows]}
    for key, c in (("Zgr", "g_grain"), ("Zur", "g_urea")):
        if c in CHANNELS:
            inp[key] = lagmat(z[c], fill=0.0)[rows]
    return inp


def residuals(post: dict, inp: dict) -> np.ndarray:
    """Standardised residual vectors [months, K] at the posterior mean (NaN where a series is missing)."""
    p = {k: v.mean(0) for k, v in post.items()}
    arr = series_arrays()
    energy = inp["Zx"] @ p["Bm"].T + np.where(arr["gsel"][None, :], inp["Zus"] @ p["Gm"].T, inp["Zeu"] @ p["Gm"].T)
    m = (p["a"] + p["S"][:, inp["mon"]].T + p["rho"] * np.nan_to_num(inp["yprev"])
         + energy * (1 + p["kappa"] * inp["D"][:, None]))
    if "Fg" in p:
        m = m + inp["Zgr"] @ p["Fg"].T
    if "Fu" in p:
        m = m + inp["Zur"] @ p["Fu"].T
    scale = p["sigma"] * np.exp(p["phi"] * inp["v"][:, None] + p["psi"] * inp["D"][:, None])
    z = (inp["y"] - m) / scale
    z[~(np.isfinite(inp["y"]) & np.isfinite(inp["yprev"]))] = np.nan
    return z


def fit(data: dict, last: int, seed: int = 0) -> tuple[dict, Stats, dict, np.ndarray]:
    """NUTS on months LAGS..last: posterior draws, standardisation, diagnostics, residual vectors."""
    st = Stats(data, last)
    inp = fit_inputs(data, st, last)
    arr = series_arrays()
    warm, samp = (40, 40) if QUICK else (WARMUP, SAMPLES)
    mcmc = MCMC(NUTS(model, target_accept_prob=0.9, max_tree_depth=8), num_warmup=warm, num_samples=samp,
                num_chains=CHAINS, chain_method="parallel", progress_bar=False)
    t0 = time.time()
    mcmc.run(jax.random.PRNGKey(seed), extra_fields=("diverging",),
             **{k: jnp.asarray(v) for k, v in inp.items()}, **{k: jnp.asarray(v) for k, v in arr.items()})
    grouped = mcmc.get_samples(group_by_chain=True)
    sites = ("B", "G", "a", "rho_raw", "kz", "mu_kappa", "psi", "sigma_raw", "phi")
    sites += tuple(s for s, c in (("Fgr", "g_grain"), ("Fur", "g_urea")) if c in CHANNELS)
    summ = numpyro.diagnostics.summary({k: np.asarray(grouped[k]) for k in sites})
    keep = series_arrays()["fmask"] > 0  # the other series' food coefficients are masked out (prior-only): skip them
    for k in ("Fgr", "Fur"):
        if k in summ:
            summ[k] = {s: np.asarray(v)[keep] for s, v in summ[k].items()}
    diag = {"seconds": round(time.time() - t0, 1), "chains": CHAINS, "warmup": warm, "samples": samp,
            "divergences": int(np.sum(mcmc.get_extra_fields()["diverging"])),
            "max_r_hat": round(max(float(np.nanmax(s["r_hat"])) for s in summ.values()), 3),
            "min_ess": round(min(float(np.nanmin(s["n_eff"])) for s in summ.values()), 1),
            "months": int(len(inp["y"])), "supply_months": int(inp["D"].sum()), "last": f"{data['months'][last]:%Y-%m}",
            "food_drivers": FOOD_MODE}
    post = {k: np.asarray(v) for k, v in mcmc.get_samples().items() if k in KEEP}
    pick = np.random.default_rng(seed).choice(len(post["a"]), size=min(50 if QUICK else DRAWS, len(post["a"])),
                                              replace=False)
    post = {k: v[pick] for k, v in post.items()}
    return post, st, diag, residuals(post, inp)


def simulate(post: dict, st: Stats, data: dict, t0: np.ndarray, fut: dict, Dfut: np.ndarray, zres: np.ndarray, rng,
             regime: bool = True) -> np.ndarray:
    """Draws of the cumulative change (% of the price level) of every series 1..hz months after each
    origin t0 [O]: [N, O, hz, K], hz = Dfut.shape[1] (H unless a run needs a longer path). fut: future
    monthly log changes of each driver channel, [N or 1, O, hz] (a missing channel is held flat); Dfut [O, hz].
    Noise: whole standardised residual vectors drawn from the training months (zres), so the series
    keep their cross-correlation; a missing entry falls back to a Student-t draw.
    regime=False switches the supply-disruption terms off (kappa = psi = 0) for the ablation."""
    N, K, O, hz = len(post["a"]), len(SERIES), len(t0), Dfut.shape[1]
    z = standardised(data, st)
    arr = series_arrays()
    f = {c: np.broadcast_to(np.nan_to_num(fut.get(c, np.zeros((1, O, hz)))) / st.sd[c], (N, O, hz)) for c in CHANNELS}
    buf = {c: np.stack([z[c][t0 - l] for l in range(LAGS)], -1)[None].repeat(N, 0) for c in CHANNELS}  # [N, O, LAGS]
    yprev = np.nan_to_num(z["y"][t0])[None].repeat(N, 0)  # [N, O, K]
    B, G, a, S, rho = post["Bm"], post["Gm"], post["a"], post["S"], post["rho"]
    kappa, psi = (post["kappa"], post["psi"]) if regime else (np.zeros_like(post["kappa"]), np.zeros_like(post["psi"]))
    phi, sig, nu = post["phi"], post["sigma"], post["nu"]
    food = [(c, post[p]) for c, p in (("g_grain", "Fg"), ("g_urea", "Fu")) if p in post and c in CHANNELS]
    cum, out = np.zeros((N, O, K)), np.zeros((N, O, hz, K))
    first = data["months"][0]
    lag = lambda b, M: np.einsum("nol,nkl->nok", b, M)  # noqa: E731
    for j in range(hz):
        for c in CHANNELS:
            buf[c] = np.concatenate([f[c][..., j:j + 1], buf[c][..., :-1]], -1)
        v = (np.log(np.abs(buf["x"][..., :3]).mean(-1) + VOL_FLOOR) - st.vm) / st.vs  # [N, O]
        energy = lag(buf["x"], B) + np.where(arr["gsel"][None, None], lag(buf["g_us"], G), lag(buf["g_eu"], G))
        mon = np.array([(first + pd.DateOffset(months=int(t) + j + 1)).month - 1 for t in t0])
        d = Dfut[:, j][None, :, None]  # [1, O, 1]
        m = a[:, None] + S[:, :, mon].transpose(0, 2, 1) + rho[:, None] * yprev + energy * (1 + kappa[:, None] * d)
        for c, M in food:
            m = m + lag(buf[c], M)
        scale = sig[:, None] * np.exp(phi[:, None] * v[..., None] + psi[:, None] * d)
        e = zres[rng.integers(0, len(zres), size=(N, O))]  # [N, O, K]
        e = np.where(np.isfinite(e), e, rng.standard_t(nu[:, None, :], size=(N, O, K)))
        m = m + e * scale
        yprev = m
        cum = cum + m * st.ys + st.ym
        out[:, :, j] = cum
    return out


def with_composites(S: np.ndarray, data: dict) -> np.ndarray:
    """Append each region's composite (weighted items + rest) to the last axis of S."""
    w = data["weights"]["w"]
    comps = []
    for r in REGIONS:
        idx, keys = composite_index(r)
        comps.append(np.tensordot(S[..., idx], np.array([w[k] for k in keys]), axes=([-1], [0])))
    return np.concatenate([S, np.stack(comps, -1)], -1)


def decompose(post: dict, st: Stats, data: dict, t: int, fut: dict, D: np.ndarray) -> dict:
    """Mean contribution of each driver group's moves after month t to every series' cumulative
    change, given the moves in `fut` and the regime path D [1, H]: {group: [H, K+3]}. Noise-free and
    additive: each group's path minus the path with every driver flat after t."""
    zres0 = np.zeros((1, len(SERIES)))
    t0 = np.array([t])
    flat = {c: np.zeros((1, 1, H)) for c in CHANNELS}
    run = lambda fx: with_composites(simulate(post, st, data, t0, fx, D, zres0, np.random.default_rng(0))[:, 0], data)  # noqa: E731
    base = run(flat)
    out = {}
    for g, chans in GROUPS.items():
        if not set(chans) & set(CHANNELS):
            continue
        out[g] = (run(flat | {c: fut[c] for c in chans if c in CHANNELS}) - base).mean(0).round(3).tolist()
    out["all_drivers"] = (run(fut) - base).mean(0).round(3).tolist()
    return out


OUT_KEYS = [s.key for s in SERIES] + [f"{r}_composite" for r in REGIONS]


# --- Brent and gas paths -----------------------------------------------------------------------

def daily_brent() -> pd.Series:
    df = pd.read_csv(md.RAW / "fred_DCOILBRENTEU.csv", parse_dates=["observation_date"])
    s = pd.to_numeric(df["DCOILBRENTEU"], errors="coerce")
    s.index = df["observation_date"]
    return s.dropna()


def levy_fit(year: int, model: str) -> dict:
    """The stored daily fit trained on every day before 1 January of `year` (runs/levy/rolling-*.json)."""
    path = LEVY_RUNS / f"rolling-{min(max(year, 1998), 2026)}.json"
    return json.loads(path.read_text())["models"][model]["params"]


def innovation_table(model: str, p: dict) -> tuple[np.ndarray, np.ndarray]:
    if model == "GARCH-CGMY":
        return lf.Levy(p["G"], p["M"], p["Y"], np.zeros(lf.K), np.zeros(lf.K)).table()
    if model == "GARCH-Student-t":
        return lf.Student(p["nu"]).table()
    raise ValueError(model)


def daily_paths(model: str, daily: pd.Series, month: pd.Timestamp, n: int, shock: np.ndarray, rng) -> np.ndarray:
    """Monthly-average Brent log changes [n, len(shock)] after month `month`, from daily GARCH paths
    with the stored innovations. shock[j] shifts the whole of month j+1 (a scenario level step; it
    does not feed the GARCH variance)."""
    p = levy_fit(month.year, model)
    mu, w, al, be = p["mu"], p["omega"], p["alpha"], p["beta"]
    upto = daily[daily.index < month + pd.DateOffset(months=1)]
    r = np.diff(np.log(upto.values))
    s = lf.garch_sigma(r, mu, w, al, be)
    s2 = np.full(n, w + al * (r[-1] - mu) ** 2 + be * s[-1] ** 2)
    cdf_tab, x_tab = innovation_table(model, p)
    this_month = upto[upto.index >= month]
    prev_avg = np.full(n, np.log(this_month.mean()))
    lp0 = np.log(upto.values[-1])
    lp, level = np.full(n, lp0), np.zeros(n)
    out = np.zeros((n, len(shock)))
    for j in range(len(shock)):
        level = level + shock[j]
        acc = np.zeros(n)
        for _ in range(DAYS):
            e = np.sqrt(s2) * np.interp(rng.random(n), cdf_tab, x_tab)
            lp = lp + mu + e
            acc += np.exp(lp + level - lp0)
            s2 = w + al * e * e + be * s2
        avg = lp0 + np.log(acc / DAYS)
        out[:, j] = avg - prev_avg
        prev_avg = avg
    return out


def garch_fit(r: np.ndarray) -> dict:
    """Monthly GARCH(1,1) with unit-variance Student-t shocks, by maximum likelihood."""
    r = r[np.isfinite(r)]

    def unpack(p):
        mu, lw, la, lb, ln = p
        a = 1 / (1 + np.exp(-la))
        b = (1 - a) * 0.999 / (1 + np.exp(-lb))
        return mu, np.exp(lw), a, b, 2.1 + np.exp(ln)

    def nll(p):
        mu, w, a, b, nu = unpack(p)
        e = r - mu
        s2 = np.empty_like(r)
        s2[0] = e.var()
        for i in range(1, len(r)):
            s2[i] = w + a * e[i - 1] ** 2 + b * s2[i - 1]
        c = np.sqrt((nu - 2) / nu)
        return -np.sum(stats.t.logpdf(e / np.sqrt(s2) / c, nu) - np.log(np.sqrt(s2) * c))

    v = r.var()
    best = min((optimize.minimize(nll, [r.mean(), np.log(v * w0), -2.0, 1.5, np.log(4.0)], method="Nelder-Mead",
                                  options={"maxiter": 4000, "xatol": 1e-6, "fatol": 1e-8}) for w0 in (0.05, 0.2)),
               key=lambda o: o.fun)
    mu, w, a, b, nu = unpack(best.x)
    e = r - mu
    s2 = e.var()
    for i in range(1, len(r) + 1):
        s2 = w + a * e[i - 1] ** 2 + b * s2
    return {"mu": float(mu), "omega": float(w), "alpha": float(a), "beta": float(b), "nu": float(nu), "s2_next": float(s2)}


def garch_paths(par: dict, n: int, shock: np.ndarray, rng) -> np.ndarray:
    """[n, len(shock)] monthly changes: mu + shock[j] + sigma_j eps_j; the scenario shock does not feed
    the variance."""
    s2 = np.full(n, par["s2_next"])
    c = np.sqrt((par["nu"] - 2) / par["nu"])
    out = np.zeros((n, len(shock)))
    for j in range(len(shock)):
        e = np.sqrt(s2) * rng.standard_t(par["nu"], n) * c
        out[:, j] = par["mu"] + shock[j] + e
        s2 = par["omega"] + par["alpha"] * e ** 2 + par["beta"] * s2
    return out


def driver_model(data: dict, last: int) -> dict:
    """Each driver channel besides Brent: beta x Brent's monthly change plus its own monthly GARCH-t
    residual, fitted on months up to `last`."""
    sl = slice(1, last + 1)
    out = {}
    for c in CHANNELS[1:]:
        x, y = data["x"][sl], data[c][sl]
        ok = np.isfinite(x) & np.isfinite(y)
        beta = float(np.polyfit(x[ok], y[ok], 1)[0])
        out[c] = garch_fit(y[ok] - beta * x[ok]) | {"beta": beta}
    return out


def closure_template(data: dict) -> dict:
    """The 2026 closure's monthly moves (log) of every driver channel, months 1..7 of the template."""
    months = data["months"]
    a, b = months.get_loc(pd.Timestamp(CLOSURE[0])), months.get_loc(pd.Timestamp(CLOSURE[1]))
    tpl = {}
    for c in CHANNELS:
        tpl[c] = np.zeros(H)
        tpl[c][:b - a + 1] = np.nan_to_num(data[c][a:b + 1])
    return tpl


def driver_paths(data: dict, last: int, n: int, rng, driver: str = "GARCH-CGMY", severity: float = 0.0,
                 dm: dict | None = None, daily: pd.Series | None = None, hz: int = H) -> dict:
    """Paths [n, hz] of every driver channel after month `last`. severity scales the 2026 closure
    template (0 = no closure). driver: GARCH-CGMY or GARCH-Student-t (daily, stored fits) or monthly-t.
    The other channels follow Brent (beta) plus their own GARCH-t noise and, in a closure, their own
    2026 moves beyond what Brent explains."""
    dm = dm or driver_model(data, last)
    tpl = ({c: np.r_[v, np.zeros(hz)][:hz] for c, v in closure_template(data).items()} if severity
           else {c: np.zeros(hz) for c in CHANNELS})
    shock = severity * tpl["x"]
    if driver == "monthly-t":
        x = garch_paths(garch_fit(data["x"][1:last + 1]), n, shock, rng)
    else:
        x = daily_paths(driver, daily if daily is not None else daily_brent(), data["months"][last], n, shock, rng)
    out = {"x": x}
    for c in CHANNELS[1:]:
        par = dm[c]
        excess = severity * np.where(tpl[c] != 0, tpl[c] - par["beta"] * tpl["x"], 0.0)
        out[c] = par["beta"] * x + garch_paths(par, n, excess, rng)
    return out


# --- scoring -----------------------------------------------------------------------------------

def crps_samples(S: np.ndarray, y: np.ndarray) -> np.ndarray:
    """CRPS of the sample distribution S [N, ...] at y [...]."""
    N = S.shape[0]
    i = np.arange(1, N + 1).reshape((-1,) + (1,) * (S.ndim - 1))
    return np.mean(np.abs(S - y), 0) - np.sum((2 * i - N - 1) * np.sort(S, 0), 0) / N ** 2


def crps_normal(mu, sd, y):
    z = (y - mu) / sd
    return sd * (z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - 1 / np.sqrt(np.pi))


def actual_paths(data: dict, t0: np.ndarray) -> np.ndarray:
    """Cumulative actual changes [O, H, K+3] after each origin (NaN beyond the data)."""
    T, K = len(data["months"]), len(SERIES)
    out = np.full((len(t0), H, K), np.nan)
    for i, t in enumerate(t0):
        n = min(H, T - 1 - t)
        out[i, :n] = np.cumsum(data["y"][t + 1:t + 1 + n], 0)
    return with_composites(out[None], data)[0]


def benchmarks(data: dict, last: int, t0: np.ndarray, actual: np.ndarray, rng, n: int = 400) -> dict:
    """CRPS [O, H, K+3] of the average link (OLS, normal errors, given oil and gas) and of
    climatology (normal with the training mean and sd of h-month changes)."""
    O, K = len(t0), len(SERIES)
    link = np.zeros((n, O, H, K))
    clim = np.zeros((n, O, H, K))
    for k in range(K):
        b, sd, X = ols_fit(data, k, last)
        y = data["y"][:last + 1, k]
        for h in range(1, H + 1):
            sums = pd.Series(y).rolling(h).sum().values
            m, s = np.nanmean(sums), np.nanstd(sums)
            clim[:, :, h - 1, k] = m + s * rng.standard_normal((n, O))
        for i, t in enumerate(t0):
            Xf = np.nan_to_num(X[t + 1:t + H + 1])
            if len(Xf) < H:
                Xf = np.vstack([Xf, np.zeros((H - len(Xf), X.shape[1]))])
            link[:, i, :, k] = np.cumsum(Xf @ b) + sd * np.sqrt(np.arange(1, H + 1)) * rng.standard_normal((n, H))
    out = {}
    for name, S in (("avg_link", link), ("climatology", clim)):
        S = with_composites(S, data)
        out[name] = {"crps": crps_samples(S, np.nan_to_num(actual)), "lo": np.quantile(S, 0.05, 0),
                     "hi": np.quantile(S, 0.95, 0)}
    return out


def score(S: np.ndarray, actual: np.ndarray) -> dict:
    lo, hi = np.quantile(S, 0.05, 0), np.quantile(S, 0.95, 0)
    return {"crps": crps_samples(S, np.nan_to_num(actual)), "lo": lo, "hi": hi}


def pack(d: dict, actual: np.ndarray) -> dict:
    """Keep the scored horizons and turn arrays into lists (NaN where the actual is missing)."""
    hi = [h - 1 for h in HS]
    ok = np.isfinite(actual[:, hi])
    out = {}
    for k, v in d.items():
        v = v[:, hi]
        out[k] = np.where(ok, v, np.nan).round(5).tolist()
    out["inside90"] = np.where(ok, (actual[:, hi] >= d["lo"][:, hi]) & (actual[:, hi] <= d["hi"][:, hi]), np.nan).tolist()
    for k in ("lo", "hi"):
        out.pop(k)
    return out


# --- runs --------------------------------------------------------------------------------------

def fold_blocks(months: pd.DatetimeIndex) -> list[np.ndarray]:
    """8 forward-chaining test blocks of origins, 2008-01..2025-12."""
    t = np.flatnonzero((months >= "2008-01-01") & (months <= "2025-12-01"))
    return np.array_split(t, 8)


def quantiles(S: np.ndarray) -> dict:
    return {f"q{int(q * 100):02d}": np.quantile(S, q, 0).round(4).tolist() for q in (0.05, 0.25, 0.5, 0.75, 0.95)}


def run_fold(data: dict, j: int) -> dict:
    """Fit on months before block j, score every origin in it: what-if (drivers and regime as they
    happened) with and without the regime terms, and forecasts with three Brent models."""
    block = fold_blocks(data["months"])[j]
    last = int(block[0] - 1)
    post, st, diag, zres = fit(data, last, seed=j)
    rng = np.random.default_rng(100 + j)
    t0 = block
    N = len(post["a"])
    actual = actual_paths(data, t0)
    T = len(data["months"])
    later = lambda a: np.stack([np.r_[np.nan_to_num(a[t + 1:t + H + 1]), np.zeros(max(0, t + H + 1 - T))] for t in t0])  # noqa: E731
    Dw = later(data["D"])
    res = {"fold": j, "diagnostics": diag, "origins": [f"{data['months'][t]:%Y-%m}" for t in t0], "modes": {}}
    whatif = {c: later(data[c])[None] for c in CHANNELS}
    for label, regime in (("whatif", True), ("whatif_no_regime", False)):
        S = with_composites(simulate(post, st, data, t0, whatif, Dw, zres, rng, regime), data)
        res["modes"][label] = pack(score(S, actual), actual)
    dm, daily = driver_model(data, last), daily_brent()
    Dfc = np.repeat(data["D"][t0][:, None], H, 1)  # a disruption under way is assumed to continue
    brent_actual = np.stack([np.cumsum(np.r_[data["x"][t + 1:t + H + 1], np.full(max(0, t + H + 1 - T), np.nan)]) * 100
                             for t in t0])
    res["brent"] = {}
    for driver in ("GARCH-CGMY", "GARCH-Student-t", "monthly-t"):
        paths = [driver_paths(data, int(t), N, rng, driver, 0.0, dm, daily) for t in t0]
        fc = {c: np.stack([p[c] for p in paths], 1) for c in CHANNELS}  # [N, O, H]
        S = with_composites(simulate(post, st, data, t0, fc, Dfc, zres, rng), data)
        res["modes"][f"forecast_{driver}"] = pack(score(S, actual), actual)
        if driver == "GARCH-CGMY" and SAVE_KEYS:
            RUNS.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(RUNS / f"fold-{j}{'-quick' if QUICK else ''}-draws.npz",
                                S=S[:, :, :3][..., [OUT_KEYS.index(k) for k in SAVE_KEYS]].astype(np.float32),
                                origins=np.array(res["origins"]), keys=np.array(SAVE_KEYS))
        B = np.cumsum(fc["x"], 2) * 100
        res["brent"][driver] = pack(score(B[..., None], brent_actual[..., None]), brent_actual[..., None])
    res["benchmarks"] = {k: pack(v, actual) for k, v in benchmarks(data, last, t0, actual, rng).items()}
    return res


def run_fold_lagged(data: dict, j: int) -> dict:
    """Forecast mode with the information the surveys had, for the comparison with the Fed and the SPF.
    A survey taken at the end of month t knows CPI to month t-1 (month t's is published two weeks into
    t+1), so for each origin t of block j the forecast starts at t-1, runs H+1 months and is scored on
    the change over months t+1..t+h, the window the surveys forecast. The same fit (seed) as the fold,
    and, from the same draws, the usual forecast from t, so the head start's worth is measured on one fit."""
    block = fold_blocks(data["months"])[j]
    last = int(block[0] - 1)
    post, st, diag, zres = fit(data, last, seed=j)
    rng = np.random.default_rng(300 + j)
    t0 = block
    N = len(post["a"])
    actual = actual_paths(data, t0)
    dm, daily = driver_model(data, last), daily_brent()
    res = {"fold": j, "diagnostics": diag, "origins": [f"{data['months'][t]:%Y-%m}" for t in t0], "modes": {}}
    for label, start, hz in (("forecast_GARCH-CGMY", t0, H), ("forecast_lagged_GARCH-CGMY", t0 - 1, H + 1)):
        paths = [driver_paths(data, int(t), N, rng, "GARCH-CGMY", 0.0, dm, daily, hz) for t in start]
        fc = {c: np.stack([p[c] for p in paths], 1) for c in CHANNELS}  # [N, O, hz]
        S = simulate(post, st, data, start, fc, np.repeat(data["D"][start][:, None], hz, 1), zres, rng)
        if hz > H:
            S = S[:, :, 1:] - S[:, :, :1]  # the change after month t, forecast from the end of t-1
        res["modes"][label] = pack(score(with_composites(S, data), actual), actual)
    res["benchmarks"] = {k: pack(v, actual) for k, v in benchmarks(data, last, t0, actual, rng).items()}
    return res


def run_event(data: dict, base_month: str, seed: int, scenarios: bool) -> dict:
    """Fit up to `base_month`; fan charts given the drivers that happened (what-if), what each
    driver group contributed, and, if `scenarios`, no closure against a 2026-sized closure at three
    severities with Lévy Brent paths."""
    months = data["months"]
    t = months.get_loc(pd.Timestamp(base_month))
    post, st, diag, zres = fit(data, t, seed=seed)
    rng = np.random.default_rng(seed + 1)
    N, T = len(post["a"]), len(months)
    n_known = min(H, T - 1 - t)
    pad = lambda a: np.r_[np.nan_to_num(a[t + 1:t + 1 + n_known]), np.zeros(H - n_known)]  # noqa: E731
    Dw = np.r_[data["D"][t + 1:t + 1 + n_known], np.ones(H - n_known)][None]
    out = {"base": base_month, "diagnostics": diag, "fans": {}, "kappa": quantiles(post["kappa"]),
           "mu_kappa": quantiles(post["mu_kappa"]), "psi": quantiles(post["psi"]),
           "actual": np.nan_to_num(actual_paths(data, np.array([t]))[0], nan=-999).round(3).tolist(),
           "actual_months": n_known}
    whatif = {c: pad(data[c])[None, None] for c in CHANNELS}
    for label, regime in (("whatif", True), ("whatif_no_regime", False)):
        S = with_composites(simulate(post, st, data, np.array([t]), whatif, Dw, zres, rng, regime), data)[:, 0]
        out["fans"][label] = quantiles(S)
    out["contributions"] = decompose(post, st, data, t, whatif, Dw)
    link = np.zeros((N, H, len(SERIES)))
    for k in range(len(SERIES)):
        b, sd, X = ols_fit(data, k, t)
        Xf = np.vstack([np.nan_to_num(X[t + 1:t + 1 + n_known]), np.zeros((H - n_known, X.shape[1]))])
        link[:, :, k] = np.cumsum(Xf @ b) + sd * np.sqrt(np.arange(1, H + 1)) * rng.standard_normal((N, H))
    out["fans"]["avg_link"] = quantiles(with_composites(link, data))
    if scenarios:
        dm, daily = driver_model(data, t), daily_brent()
        for label, sev in (("none", 0.0), ("closure_25", 0.25), ("closure_50", 0.5), ("closure_100", 1.0)):
            p = driver_paths(data, t, N, rng, "GARCH-CGMY", sev, dm, daily)
            D = np.ones((1, H)) if sev > 0 else np.zeros((1, H))
            S = with_composites(simulate(post, st, data, np.array([t]), {c: p[c][:, None] for c in CHANNELS}, D, zres,
                                         rng), data)[:, 0]
            out["fans"][label] = quantiles(S)
            out["fans"][label + "_brent"] = quantiles(np.cumsum(p["x"], 1) * 100)
    return out


def run_final(data: dict) -> dict:
    """Fit on all months: kappa by kind; each item's 12-month response to a sustained +10% move in
    Brent (normal and supply-disruption months) and, with food drivers, in grains and in urea; and
    the next 12 months' fan from the latest month with Lévy Brent paths (the disruption continuing)."""
    months = data["months"]
    last = len(months) - 1
    post, st, diag, zres = fit(data, last, seed=99)
    rng = np.random.default_rng(7)
    N = len(post["a"])
    t0 = np.array([last])

    def response(channel: str, d: float) -> dict:
        shocked = np.zeros((1, 1, H))
        shocked[..., 0] = SHOCK
        seed = int(rng.integers(1 << 30))
        D = np.full((1, H), d)
        S1 = simulate(post, st, data, t0, {channel: shocked}, D, zres, np.random.default_rng(seed))
        S0 = simulate(post, st, data, t0, {}, D, zres, np.random.default_rng(seed))
        return quantiles(with_composites(S1 - S0, data)[:, 0])  # common random numbers cancel the noise

    resp = {"normal": response("x", 0.0), "supply": response("x", 1.0)}
    resp |= {name: response(c, 0.0) for name, c in (("grain", "g_grain"), ("urea", "g_urea")) if c in CHANNELS}
    w = data["weights"]["w"]
    p = driver_paths(data, last, N, rng, "GARCH-CGMY", 0.0, driver_model(data, last), daily_brent())
    S = with_composites(simulate(post, st, data, t0, {c: p[c][:, None] for c in CHANNELS},
                                 np.full((1, H), data["D"][last]), zres, rng), data)[:, 0]
    return {"diagnostics": diag, "kappa": quantiles(post["kappa"]), "mu_kappa": quantiles(post["mu_kappa"]),
            "psi": quantiles(post["psi"]), "phi": quantiles(post["phi"]), "response_10pct": resp,
            "weights": {k: w.get(k) for k in OUT_KEYS}, "outlook": quantiles(S), "outlook_brent": quantiles(np.cumsum(p["x"], 1) * 100),
            "latest": f"{months[last]:%Y-%m}", "in_supply_regime": bool(data["D"][last])}


def run(data: dict, name: str) -> dict:
    meta = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "job": os.environ.get("SLURM_JOB_ID"),
            "quick": QUICK, "food_drivers": FOOD_MODE, "samples": SAMPLES}
    if name.startswith("fold-") and name.endswith("-lagged"):
        out = run_fold_lagged(data, int(name.split("-")[1]))
    elif name.startswith("fold-"):
        out = run_fold(data, int(name.split("-")[1]))
    elif name == "event-2022":
        out = run_event(data, "2022-02-01", seed=22, scenarios=False)
    elif name == "event-2026":
        out = run_event(data, "2026-02-01", seed=26, scenarios=True)
    elif name == "final":
        out = run_final(data)
    else:
        raise SystemExit(f"unknown fit {name}")
    out |= {"meta": meta, "keys": OUT_KEYS}
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{name}{'-quick' if QUICK else ''}.json").write_text(json.dumps(out))
    print(f"{name}: {out.get('diagnostics')}", flush=True)
    return out


NAMES = ["event-2026", "event-2022", "final"] + [f"fold-{j}" for j in range(8)]


def main() -> None:
    global QUICK
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("events", "fit", "all", "check", "report"))
    p.add_argument("name", nargs="?", default="final")
    p.add_argument("--quick", action="store_true", help="tiny sampler settings, to smoke-test a fit")
    a = p.parse_args()
    QUICK = a.quick or a.cmd == "check"
    if a.cmd == "report":
        import cost_of_living_report as rep  # noqa: PLC0415
        return rep.write()
    data = load()
    if a.cmd == "events":
        for r in event_table(data):
            print({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()})
        for r in fuel_ratios():
            print(r)
        print(fuel_average_links())
        print(data["weights"])
    elif a.cmd == "check":
        run(data, a.name)
    elif a.cmd == "fit":
        run(data, a.name)
    else:
        for n in NAMES:
            run(data, n)


if __name__ == "__main__":
    main()
