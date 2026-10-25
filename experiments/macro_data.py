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

import io
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
    geo: str = ""  # sector and goods rows: country code (Eurostat geo, US)
    item: str = ""  # sector and goods rows: industry or good (NACE, COICOP, BLS or World Bank code)


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
    # Oil stocks beyond the fuel block (EIA weekly, no key needed), US. Optional: not in BLOCKS, so the
    # runs so far are unchanged; macro_nn's `v1_stocks` and `v1_fuel_stocks` variants test them.
    Series("gasoline_stocks", "eia", "WGTSTUS1", "stocks", "dlog", 0, name="US motor gasoline stocks (EIA)"),
    Series("distillate_stocks", "eia", "WDISTUS1", "stocks", "dlog", 0, name="US distillate fuel oil stocks (EIA)"),
    Series("total_stocks", "eia", "WTTSTUS1", "stocks", "dlog", 0,
           name="US crude oil and petroleum product stocks, including the SPR (EIA)"),
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
OPTIONAL = ("stocks",)  # registered and fetched, but only used by variants that ask for them
SECTOR_BLOCKS = ("oil", "sectors", "commodities")  # the sector runs: industries by country, world metal prices
GOODS_BLOCKS = ("oil", "goods", "household", "world")  # the goods runs: specific goods by country, world prices
NATION_BLOCKS = ("oil", "nations")  # the nations runs: consumer and producer prices in ~170 countries
OILFLOW_BLOCKS = ("oil", "oilflows")  # the oil-flow runs: crude and product flows in ~115 countries (JODI)
MARKET_BLOCKS = ("oil", "world", "markets")  # the commodity runs: every world price, by kind of commodity
ALL_BLOCKS = BLOCKS + SECTOR_BLOCKS[1:] + GOODS_BLOCKS[1:] + NATION_BLOCKS[1:] + OILFLOW_BLOCKS[1:] + MARKET_BLOCKS[2:]
GENERATED = ("sectors", "goods", "household", "world", "nations", "oilflows", "markets")  # kept only with enough live data
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
SECTOR_MIN_MONTHS, SECTOR_LIVE_FROM = 120, "2025-01-01"  # a GENERATED row needs both to enter the panel

# Specific goods (the goods runs). European goods are the finest NACE classes Eurostat publishes
# (producer prices and output, as for the sectors), kept where at least two countries had 10+ years
# on 2026-10-25. US goods are BLS commodity PPIs on FRED. Household goods are HICP sub-indices
# (Eurostat prc_hicp_minr, COICOP 2018, 2015 = 100, from 1996). World prices are the World Bank's
# monthly Pink Sheet.
GOODS = [  # (NACE class, good)
    ("C1011", "Meat"), ("C1041", "Oils and fats"), ("C1051", "Dairy products"), ("C1061", "Flour and grain mill products"),
    ("C1071", "Bread and fresh pastry"), ("C1081", "Sugar"), ("C1091", "Farm animal feed"), ("C1711", "Pulp"),
    ("C1712", "Paper and paperboard"), ("C1721", "Corrugated paper and packaging"), ("C2011", "Industrial gases"),
    ("C2013", "Inorganic basic chemicals"), ("C2014", "Organic basic chemicals"), ("C2015", "Fertilisers"),
    ("C2016", "Plastics in primary forms"), ("C2017", "Synthetic rubber"), ("C2211", "Tyres"),
    ("C2221", "Plastic plates, sheets and film"), ("C2222", "Plastic packaging"), ("C2311", "Flat glass"),
    ("C2313", "Hollow glass (bottles, jars)"), ("C2332", "Bricks and tiles"), ("C2351", "Cement"),
    ("C2352", "Lime and plaster"), ("C2363", "Ready-mixed concrete"), ("C2434", "Steel wire"), ("C2442", "Aluminium"),
    ("C2444", "Copper"), ("C2451", "Iron castings"), ("C2592", "Light metal packaging (cans)"),
]
US_GOODS = [  # (BLS commodity code on FRED, good)
    ("WPU0571", "Gasoline"), ("WPU057303", "Diesel (No. 2)"), ("WPU057203", "Jet fuel"), ("WPU0574", "Residual fuel oil"),
    ("WPU0578", "Lubricating oil base stocks"), ("WPU058102", "Asphalt"), ("WPU0532", "Natural gas liquids"),
    ("WPU0543", "Industrial electric power"), ("WPU0553", "Industrial natural gas"),
    ("WPU0613", "Basic inorganic chemicals"), ("WPU0614", "Basic organic chemicals"), ("WPU0652", "Fertiliser materials"),
    ("WPU065201", "Nitrogen fertilisers"), ("WPU0652013A", "Ammonia, nitric acid, ammonium compounds and urea"),
    ("WPU0651", "Mixed fertilisers"), ("WPU0662", "Thermoplastic resins (polyethylene, PVC, ...)"),
    ("WPU0663", "Thermosetting resins"), ("WPU06790918", "Carbon black"), ("WPU0711", "Synthetic rubber"),
    ("WPU0712", "Tyres"), ("WPU0914", "Paperboard"), ("WPU091203", "Corrugated recyclable paper"),
    ("WPU09150301", "Corrugated shipping containers"), ("WPU1011", "Iron ore"), ("WPU1012", "Iron and steel scrap"),
    ("WPU1017", "Steel mill products"), ("WPU101707", "Cold rolled steel sheet"), ("WPU101706", "Steel pipe and tube"),
    ("WPU101705", "Steel wire"), ("WPU1022", "Primary nonferrous metals"), ("WPU102301", "Copper scrap"),
    ("WPU102302", "Aluminium scrap"), ("WPU102501", "Aluminium mill shapes"), ("WPU102502", "Copper and brass mill shapes"),
    ("WPU1026", "Nonferrous wire and cable"), ("WPU103103", "Aluminium cans"), ("WPU1322", "Cement"),
    ("WPU1333", "Ready-mix concrete"), ("WPU1311", "Flat glass"), ("WPU0212", "Flour"), ("WPU0211", "Bakery products"),
    ("WPU0221", "Meat"), ("WPU0231", "Fluid milk products"), ("WPU0253", "Refined sugar"),
    ("WPU0278", "Shortening and cooking oil"), ("WPU0293", "Animal feed"),
]
HOUSEHOLD = [  # (COICOP 2018 code, good)
    ("CP01", "Food and non-alcoholic drinks"), ("CP0111", "Cereals and bread"), ("CP0112", "Meat"),
    ("CP0114", "Milk, dairy and eggs"), ("CP0115", "Oils and fats"), ("CP0118", "Sugar and confectionery"),
    ("CP0451", "Electricity"), ("CP0452", "Gas"), ("CP0453", "Heating oil"), ("CP0454", "Solid fuels"),
    ("CP0722", "Motor fuels"), ("CP07221", "Diesel"), ("CP07222", "Petrol"), ("CP0731", "Rail fares"), ("CP0733", "Air fares"),
]
HOUSEHOLD_COUNTRIES = COUNTRIES | {"GE": "Georgia", "XK": "Kosovo"}
WORLD = [  # (World Bank Pink Sheet column, good, unit); crude oil is left out, Brent is the input
    ("Coal, Australian", "Coal, Australia", "$/mt"), ("Coal, South African **", "Coal, South Africa", "$/mt"),
    ("Natural gas, US", "Natural gas, US", "$/mmbtu"), ("Natural gas, Europe", "Natural gas, Europe", "$/mmbtu"),
    ("Liquefied natural gas, Japan", "LNG, Japan", "$/mmbtu"), ("Cocoa", "Cocoa", "$/kg"),
    ("Coffee, Arabica", "Coffee, Arabica", "$/kg"), ("Coffee, Robusta", "Coffee, Robusta", "$/kg"),
    ("Tea, avg 3 auctions", "Tea", "$/kg"), ("Coconut oil", "Coconut oil", "$/mt"), ("Groundnuts", "Groundnuts", "$/mt"),
    ("Fish meal", "Fish meal", "$/mt"), ("Palm oil", "Palm oil", "$/mt"), ("Palm kernel oil", "Palm kernel oil", "$/mt"),
    ("Soybeans", "Soybeans", "$/mt"), ("Soybean oil", "Soybean oil", "$/mt"), ("Soybean meal", "Soybean meal", "$/mt"),
    ("Rapeseed oil", "Rapeseed oil", "$/mt"), ("Sunflower oil", "Sunflower oil", "$/mt"), ("Barley", "Barley", "$/mt"),
    ("Maize", "Maize", "$/mt"), ("Sorghum", "Sorghum", "$/mt"), ("Rice, Thai 5%", "Rice, Thai 5%", "$/mt"),
    ("Wheat, US SRW", "Wheat, US soft red", "$/mt"), ("Wheat, US HRW", "Wheat, US hard red", "$/mt"),
    ("Banana, Europe", "Bananas, Europe", "$/kg"), ("Orange", "Oranges", "$/kg"), ("Beef **", "Beef", "$/kg"),
    ("Chicken **", "Chicken", "$/kg"), ("Lamb **", "Lamb", "$/kg"), ("Shrimps, Mexican", "Shrimp", "$/kg"),
    ("Sugar, EU", "Sugar, EU", "$/kg"), ("Sugar, US", "Sugar, US", "$/kg"), ("Sugar, world", "Sugar, world", "$/kg"),
    ("Tobacco, US import u.v.", "Tobacco", "$/mt"), ("Logs, Malaysian", "Logs, Malaysia", "$/m3"),
    ("Sawnwood, Malaysian", "Sawnwood, Malaysia", "$/m3"), ("Plywood", "Plywood", "cents/sheet"),
    ("Cotton, A Index", "Cotton", "$/kg"), ("Rubber, TSR20 **", "Rubber, TSR20", "$/kg"), ("Rubber, RSS3", "Rubber, RSS3", "$/kg"),
    ("Phosphate rock", "Phosphate rock", "$/mt"), ("DAP", "DAP fertiliser", "$/mt"), ("TSP", "TSP fertiliser", "$/mt"),
    ("Urea", "Urea", "$/mt"), ("Potassium chloride **", "Potash", "$/mt"), ("Aluminum", "Aluminium", "$/mt"),
    ("Iron ore, cfr spot", "Iron ore", "$/dmtu"), ("Copper", "Copper", "$/mt"), ("Lead", "Lead", "$/mt"),
    ("Tin", "Tin", "$/mt"), ("Nickel", "Nickel", "$/mt"), ("Zinc", "Zinc", "$/mt"), ("Gold", "Gold", "$/troy oz"),
    ("Platinum", "Platinum", "$/troy oz"), ("Silver", "Silver", "$/troy oz"),
]
# Kinds of commodity, for the commodity runs' breakdown (a world price's `item`).
KINDS = [("energy", "Energy"), ("metals", "Base metals and iron ore"), ("precious", "Precious metals"),
         ("fertilisers", "Fertilisers"), ("food", "Food"), ("beverages", "Beverages"),
         ("raw", "Agricultural raw materials"), ("indices", "Price indices (IMF, FAO)")]
WORLD_KIND = {
    **dict.fromkeys(["Coal, Australia", "Coal, South Africa", "Natural gas, US", "Natural gas, Europe", "LNG, Japan"], "energy"),
    **dict.fromkeys(["Cocoa", "Coffee, Arabica", "Coffee, Robusta", "Tea"], "beverages"),
    **dict.fromkeys(["Tobacco", "Logs, Malaysia", "Sawnwood, Malaysia", "Plywood", "Cotton", "Rubber, TSR20",
                     "Rubber, RSS3"], "raw"),
    **dict.fromkeys(["Phosphate rock", "DAP fertiliser", "TSP fertiliser", "Urea", "Potash"], "fertilisers"),
    **dict.fromkeys(["Aluminium", "Iron ore", "Copper", "Lead", "Tin", "Nickel", "Zinc"], "metals"),
    **dict.fromkeys(["Gold", "Platinum", "Silver"], "precious"),
}  # every other WORLD good is food
# The `markets` block: world prices the Pink Sheet doesn't have. IMF primary commodity prices and
# indices (FRED, monthly averages), US refined-product spot prices (EIA via FRED, daily; known the
# same month, like Brent) and the FAO food price index with its sub-indices.
MARKETS = [  # (source, code, name, kind, publication lag)
    ("fred", "PWOOLCUSDM", "Wool, coarse (IMF)", "raw", 1), ("fred", "PWOOLFUSDM", "Wool, fine (IMF)", "raw", 1),
    ("fred", "PHIDEUSDM", "Hides (IMF)", "raw", 1), ("fred", "PLOGSKUSDM", "Soft logs (IMF)", "raw", 1),
    ("fred", "PPORKUSDM", "Pork (IMF)", "food", 1), ("fred", "PSALMUSDM", "Salmon (IMF)", "food", 1),
    ("fred", "POLVOILUSDM", "Olive oil (IMF)", "food", 1), ("fred", "PBARLUSDM", "Barley (IMF)", "food", 1),
    ("fred", "PALLFNFINDEXM", "IMF all-commodity price index", "indices", 1),
    ("fred", "PNRGINDEXM", "IMF energy price index", "indices", 1),
    ("fred", "PMETAINDEXM", "IMF metals price index", "indices", 1),
    ("fred", "PINDUINDEXM", "IMF industrial inputs price index", "indices", 1),
    ("fred", "PRAWMINDEXM", "IMF agricultural raw materials price index", "indices", 1),
    ("fred", "PBEVEINDEXM", "IMF beverages price index", "indices", 1),
    ("fred", "PFOODINDEXM", "IMF food price index", "indices", 1),
    ("fred", "DDFUELNYH", "Ultra-low sulfur diesel, New York Harbor, $/gal (EIA)", "energy", 0),
    ("fred", "DDFUELUSGULF", "Ultra-low sulfur diesel, US Gulf Coast, $/gal (EIA)", "energy", 0),
    ("fred", "DDFUELLA", "Ultra-low sulfur diesel, Los Angeles, $/gal (EIA)", "energy", 0),
    ("fred", "DJFUELUSGULF", "Jet fuel, US Gulf Coast, $/gal (EIA)", "energy", 0),
    ("fred", "DHOILNYH", "Heating oil, New York Harbor, $/gal (EIA)", "energy", 0),
    ("fred", "DGASNYH", "Conventional gasoline, New York Harbor, $/gal (EIA)", "energy", 0),
    ("fred", "DGASUSGULF", "Conventional gasoline, US Gulf Coast, $/gal (EIA)", "energy", 0),
    ("fred", "DPROPANEMBTX", "Propane, Mont Belvieu, $/gal (EIA)", "energy", 0),
    ("fao", "Food Price Index", "FAO food price index", "indices", 1), ("fao", "Meat", "FAO meat price index", "indices", 1),
    ("fao", "Dairy", "FAO dairy price index", "indices", 1), ("fao", "Cereals", "FAO cereals price index", "indices", 1),
    ("fao", "Oils", "FAO vegetable oils price index", "indices", 1), ("fao", "Sugar", "FAO sugar price index", "indices", 1),
]
FAO_URL = "https://www.fao.org/media/docs/worldfoodsituationlibraries/wfs-library/food_price_indices_data.csv"

# Oil flows by country (the `oilflows` block): the JODI Oil World database (Joint Organisations Data
# Initiative), monthly, in thousand barrels a day, published about two months on. Many values carry
# JODI's assessment code 3 (not assessed); they are used as published. Countries: every reporting
# area in 2025, by its JODI (ISO 3166 alpha-2) code.
JODI_PAGE = "https://www.jodidata.org/oil/database/data-downloads.aspx"
JODI_FLOWS = [  # (file, product, flow, target group, what)
    ("primary", "TOTCRUDE", "INDPROD", "production", "crude oil production"),
    ("primary", "TOTCRUDE", "TOTIMPSB", "imports", "crude oil imports"),
    ("primary", "TOTCRUDE", "TOTEXPSB", "exports", "crude oil exports"),
    ("primary", "TOTCRUDE", "REFINOBS", "refining", "refinery crude intake"),
    ("secondary", "TOTPRODS", "REFGROUT", "refining", "refinery output of oil products"),
    ("secondary", "TOTPRODS", "TOTIMPSB", "imports", "oil product imports"),
    ("secondary", "TOTPRODS", "TOTEXPSB", "exports", "oil product exports"),
    ("secondary", "TOTPRODS", "TOTDEMO", "demand", "oil product demand"),
    ("secondary", "GASOLINE", "TOTDEMO", "demand", "gasoline demand"),
    ("secondary", "GASDIES", "TOTDEMO", "demand", "diesel and gasoil demand"),
    ("secondary", "JETKERO", "TOTDEMO", "demand", "jet fuel demand"),
    ("secondary", "RESFUEL", "TOTDEMO", "demand", "fuel oil demand"),
    ("secondary", "LPG", "TOTDEMO", "demand", "LPG demand"),
]
JODI_COUNTRIES = {  # JODI area code: (ISO 3166 alpha-3, name)
    "AE": ("ARE", "United Arab Emirates"), "AL": ("ALB", "Albania"), "AM": ("ARM", "Armenia"),
    "AO": ("AGO", "Angola"), "AR": ("ARG", "Argentina"), "AT": ("AUT", "Austria"),
    "AU": ("AUS", "Australia"), "AZ": ("AZE", "Azerbaijan"), "BB": ("BRB", "Barbados"),
    "BD": ("BGD", "Bangladesh"), "BE": ("BEL", "Belgium"), "BG": ("BGR", "Bulgaria"),
    "BH": ("BHR", "Bahrain"), "BM": ("BMU", "Bermuda"), "BN": ("BRN", "Brunei Darussalam"),
    "BO": ("BOL", "Bolivia"), "BR": ("BRA", "Brazil"), "BY": ("BLR", "Belarus"),
    "BZ": ("BLZ", "Belize"), "CA": ("CAN", "Canada"), "CH": ("CHE", "Switzerland"),
    "CL": ("CHL", "Chile"), "CN": ("CHN", "China"), "CO": ("COL", "Colombia"),
    "CR": ("CRI", "Costa Rica"), "CU": ("CUB", "Cuba"), "CY": ("CYP", "Cyprus"),
    "CZ": ("CZE", "Czechia"), "DE": ("DEU", "Germany"), "DK": ("DNK", "Denmark"),
    "DO": ("DOM", "Dominican Republic"), "DZ": ("DZA", "Algeria"), "EC": ("ECU", "Ecuador"),
    "EE": ("EST", "Estonia"), "EG": ("EGY", "Egypt, Arab Rep."), "ES": ("ESP", "Spain"),
    "FI": ("FIN", "Finland"), "FR": ("FRA", "France"), "GA": ("GAB", "Gabon"),
    "GB": ("GBR", "United Kingdom"), "GD": ("GRD", "Grenada"), "GE": ("GEO", "Georgia"),
    "GM": ("GMB", "Gambia, The"), "GQ": ("GNQ", "Equatorial Guinea"), "GR": ("GRC", "Greece"),
    "GT": ("GTM", "Guatemala"), "GY": ("GUY", "Guyana"), "HK": ("HKG", "Hong Kong SAR, China"),
    "HN": ("HND", "Honduras"), "HR": ("HRV", "Croatia"), "HT": ("HTI", "Haiti"),
    "HU": ("HUN", "Hungary"), "ID": ("IDN", "Indonesia"), "IE": ("IRL", "Ireland"),
    "IN": ("IND", "India"), "IQ": ("IRQ", "Iraq"), "IR": ("IRN", "Iran, Islamic Rep."),
    "IS": ("ISL", "Iceland"), "IT": ("ITA", "Italy"), "JM": ("JAM", "Jamaica"),
    "JP": ("JPN", "Japan"), "KR": ("KOR", "Korea, Rep."), "KW": ("KWT", "Kuwait"),
    "KZ": ("KAZ", "Kazakhstan"), "LT": ("LTU", "Lithuania"), "LU": ("LUX", "Luxembourg"),
    "LV": ("LVA", "Latvia"), "LY": ("LBY", "Libya"), "MA": ("MAR", "Morocco"),
    "MD": ("MDA", "Moldova"), "MK": ("MKD", "North Macedonia"), "MM": ("MMR", "Myanmar"),
    "MT": ("MLT", "Malta"), "MU": ("MUS", "Mauritius"), "MX": ("MEX", "Mexico"),
    "MY": ("MYS", "Malaysia"), "NE": ("NER", "Niger"), "NG": ("NGA", "Nigeria"),
    "NI": ("NIC", "Nicaragua"), "NL": ("NLD", "Netherlands"), "NO": ("NOR", "Norway"),
    "NP": ("NPL", "Nepal"), "NZ": ("NZL", "New Zealand"), "OM": ("OMN", "Oman"),
    "PA": ("PAN", "Panama"), "PE": ("PER", "Peru"), "PG": ("PNG", "Papua New Guinea"),
    "PH": ("PHL", "Philippines"), "PL": ("POL", "Poland"), "PT": ("PRT", "Portugal"),
    "PY": ("PRY", "Paraguay"), "QA": ("QAT", "Qatar"), "RO": ("ROU", "Romania"),
    "RS": ("SRB", "Serbia"), "RU": ("RUS", "Russian Federation"), "SA": ("SAU", "Saudi Arabia"),
    "SD": ("SDN", "Sudan"), "SE": ("SWE", "Sweden"), "SG": ("SGP", "Singapore"),
    "SI": ("SVN", "Slovenia"), "SK": ("SVK", "Slovak Republic"), "SR": ("SUR", "Suriname"),
    "SV": ("SLV", "El Salvador"), "SY": ("SYR", "Syrian Arab Republic"), "SZ": ("SWZ", "Eswatini"),
    "TH": ("THA", "Thailand"), "TJ": ("TJK", "Tajikistan"), "TN": ("TUN", "Tunisia"),
    "TR": ("TUR", "Turkiye"), "TT": ("TTO", "Trinidad and Tobago"), "UA": ("UKR", "Ukraine"),
    "US": ("USA", "United States"), "UY": ("URY", "Uruguay"), "VE": ("VEN", "Venezuela, RB"),
    "VN": ("VNM", "Viet Nam"), "YE": ("YEM", "Yemen, Rep."), "ZA": ("ZAF", "South Africa"),
    "TW": ("TWN", "Taiwan, China"),
}
WB_COUNTRIES = "https://api.worldbank.org/v2/country?format=json&per_page=400"  # regions and income groups

# kind: (Eurostat dataset and filters, item dimension, items, cache tag); codes are "kind:geo:item"
EUROSTAT_PANELS = {
    "price": (EUROSTAT_SECTORS["price"], "nace_r2", SECTORS, "sectors"),
    "output": (EUROSTAT_SECTORS["output"], "nace_r2", SECTORS, "sectors"),
    "goods_price": (EUROSTAT_SECTORS["price"], "nace_r2", GOODS, "goods"),
    "goods_output": (EUROSTAT_SECTORS["output"], "nace_r2", GOODS, "goods"),
    "consumer": ("prc_hicp_minr?unit=I15&freq=M", "coicop18", HOUSEHOLD, "household"),
}
WB_PAGE = "https://www.worldbank.org/en/research/commodity-markets"

# Nations (the nations runs): monthly consumer and producer prices of every country in the World
# Bank's Global Database of Inflation (Ha, Kose and Ohnsorge), compiled from national sources and
# the IMF. Its vintage on 2026-10-25 ends at 2025-03 and many countries end in 2024, so a nation row
# counts as live with data from NATIONS_LIVE_FROM on. Countries listed: 10+ years since 2000 and data
# in 2024 or later for at least one measure.
# Where a country has no energy price index, the database's energy sheet carries its housing,
# water, electricity, gas and other fuels index (COICOP 04, mostly rents) instead; those rows are a
# separate group ("utilities"), never mixed with real energy prices.
NATION_MEASURES = [  # (sheet, target group, measure)
    ("hcpi_m", "headline", "headline consumer prices"), ("ecpi_m", "energy", "energy consumer prices"),
    ("ecpi_m_housing", "utilities", "housing and utilities consumer prices (COICOP 04)"),
    ("fcpi_m", "food", "food consumer prices"), ("ppi_m", "producer", "producer prices"),
]
NATIONS = {  # ISO 3166 alpha-3 code: the database's country name
    "AFG": "Afghanistan", "AGO": "Angola", "ALB": "Albania", "ARE": "United Arab Emirates", "ARM": "Armenia",
    "ATG": "Antigua and Barbuda", "AUT": "Austria", "AZE": "Azerbaijan", "BDI": "Burundi", "BEL": "Belgium",
    "BEN": "Benin", "BFA": "Burkina Faso", "BGD": "Bangladesh", "BGR": "Bulgaria", "BHR": "Bahrain",
    "BHS": "Bahamas", "BIH": "Bosnia and Herzegovina", "BLR": "Belarus", "BLZ": "Belize", "BOL": "Bolivia",
    "BRA": "Brazil", "BRB": "Barbados", "BRN": "Brunei Darussalam", "BTN": "Bhutan", "BWA": "Botswana",
    "CAF": "Central African Republic", "CAN": "Canada", "CHE": "Switzerland", "CHL": "Chile", "CHN": "China",
    "CIV": "CÃ´te d'Ivoire", "CMR": "Cameroon", "COG": "Congo, Rep.", "COL": "Colombia", "CPV": "Cabo Verde",
    "CRI": "Costa Rica", "CYP": "Cyprus", "CZE": "Czech Republic", "DEU": "Germany", "DJI": "Djibouti",
    "DMA": "Dominica", "DNK": "Denmark", "DOM": "Dominican Republic", "DZA": "Algeria", "ECU": "Ecuador",
    "EGY": "Egypt, Arab Rep.", "ESP": "Spain", "EST": "Estonia", "ETH": "Ethiopia", "FIN": "Finland",
    "FJI": "Fiji", "FRA": "France", "GAB": "Gabon", "GBR": "United Kingdom", "GEO": "Georgia",
    "GHA": "Ghana", "GIN": "Guinea", "GMB": "Gambia, The", "GRC": "Greece", "GRD": "Grenada",
    "GTM": "Guatemala", "GUY": "Guyana", "HKG": "Hong Kong SAR, China", "HND": "Honduras", "HRV": "Croatia",
    "HTI": "Haiti", "HUN": "Hungary", "IDN": "Indonesia", "IND": "India", "IRL": "Ireland",
    "IRN": "Iran, Islamic Rep.", "ISL": "Iceland", "ISR": "Israel", "ITA": "Italy", "JAM": "Jamaica",
    "JOR": "Jordan", "JPN": "Japan", "KAZ": "Kazakhstan", "KEN": "Kenya", "KHM": "Cambodia",
    "KIR": "Kiribati", "KNA": "St. Kitts and Nevis", "KOR": "Korea, Rep.", "KWT": "Kuwait", "LAO": "Lao, PDR",
    "LBN": "Lebanon", "LBR": "Liberia", "LBY": "Libya", "LCA": "St. Lucia", "LKA": "Sri Lanka",
    "LSO": "Lesotho", "LTU": "Lithuania", "LUX": "Luxembourg", "LVA": "Latvia", "MAC": "Macao SAR, China",
    "MAR": "Morocco", "MDA": "Moldova, Rep.", "MDV": "Maldives", "MEX": "Mexico", "MKD": "North Macedonia",
    "MLI": "Mali", "MLT": "Malta", "MNE": "Montenegro", "MNG": "Mongolia", "MOZ": "Mozambique",
    "MRT": "Mauritania", "MSR": "Montserratit", "MUS": "Mauritius", "MWI": "Malawi", "MYS": "Malaysia",
    "NAM": "Namibia", "NER": "Niger", "NGA": "Nigeria", "NIC": "Nicaragua", "NLD": "Netherlands",
    "NOR": "Norway", "NPL": "Nepal", "OMN": "Oman", "PAK": "Pakistan", "PAN": "Panama",
    "PER": "Peru", "PHL": "Philippines", "POL": "Poland", "PRT": "Portugal", "PRY": "Paraguay",
    "PSE": "West Bank and Gaza", "QAT": "Qatar", "ROU": "Romania", "RUS": "Russian Federation", "RWA": "Rwanda",
    "SAU": "Saudi Arabia", "SEN": "Senegal", "SGP": "Singapore", "SLB": "Solomon Islands", "SLE": "Sierra Leone",
    "SLV": "El Salvador", "SMR": "San Marino", "SRB": "Serbia", "SSD": "South Sudan", "STP": "Sao Tome and Principe",
    "SUR": "Suriname", "SVK": "Slovakia", "SVN": "Slovenia", "SWE": "Sweden", "SYC": "Seychelles",
    "TCD": "Chad", "TGO": "Togo", "THA": "Thailand", "TJK": "Tajikistan", "TLS": "Timor-Leste",
    "TON": "Tonga", "TTO": "Trinidad and Tobago", "TUN": "Tunisia", "TUR": "Turkey", "TWN": "Taiwan, China",
    "TZA": "Tanzania, United Rep.", "UGA": "Uganda", "UKR": "Ukraine", "URY": "Uruguay", "USA": "United States",
    "UZB": "Uzbekistan", "VCT": "St. Vincent and the Grenadines", "VEN": "Venezuela, RB", "VNM": "Vietnam", "WSM": "Samoa",
    "XKX": "Kosovo", "ZAF": "South Africa", "ZMB": "Zambia",
}
NATIONS_LIVE_FROM = "2024-01-01"
INFL_PAGE = "https://www.worldbank.org/en/research/brief/inflation-database"
INFL_FILE = r"https://thedocs\.worldbank\.org/[^\"' ]*Inflation-data\.xlsx"
WB_FILE = r"https://thedocs\.worldbank\.org/[^\"' ]*CMO-Historical-Data-Monthly\.xlsx"  # the address changes monthly


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
            rows += [Series(f"{kind}_{geo.lower()}_{nace.lower()}", "eurostat_panel", f"{kind}:{geo}:{nace}",
                            "sectors", "dlog", 2, kind, f"{country}: {industry} {what} (Eurostat {dataset}, {nace})",
                            geo=geo, item=nace)
                     for geo, country in COUNTRIES.items()]
        for kind, code, what in (("price", us_ppi, "producer prices (BLS PPI"), ("output", us_ip, "output (Fed")):
            if code:
                rows.append(Series(f"{kind}_us_{nace.lower()}", "fred", code, "sectors", "dlog", 1, kind,
                                   f"United States: {industry} {what} {code}, closest NAICS)", geo="US", item=nace))
    return rows


def nation_series() -> list[Series]:
    """The nations runs' targets: each NATION_MEASURES measure in each of NATIONS. As for the
    sectors, build_panel skips the pairs a country doesn't publish, or publishes too briefly."""
    return [Series(f"nation_{group}_{iso.lower()}", "wb_inflation", f"{sheet}:{iso}", "nations", "dlog", 1, group,
                   f"{country}: {measure} (World Bank inflation database)", geo=iso, item=sheet)
            for sheet, group, measure in NATION_MEASURES for iso, country in NATIONS.items()]


def goods_series() -> list[Series]:
    """The goods runs' targets: producer prices ("price") and output ("output") of GOODS in every
    country (Eurostat) and of US_GOODS (BLS), consumer prices ("consumer") of HOUSEHOLD goods in
    every country (Eurostat HICP), and WORLD prices ("commodity"). As for the sectors, build_panel
    skips pairs that are not published, too short or stopped."""
    rows = []
    for nace, good in GOODS:
        for kind, what in (("price", "producer prices"), ("output", "output")):
            dataset = EUROSTAT_SECTORS[kind].split("?")[0]
            rows += [Series(f"good_{kind}_{geo.lower()}_{nace.lower()}", "eurostat_panel", f"goods_{kind}:{geo}:{nace}",
                            "goods", "dlog", 2, kind, f"{country}: {good} {what} (Eurostat {dataset}, {nace})",
                            geo=geo, item=nace) for geo, country in COUNTRIES.items()]
    rows += [Series(f"good_price_us_{code.lower()}", "fred", code, "goods", "dlog", 1, "price",
                    f"United States: {good} producer prices (BLS {code})", geo="US", item=code) for code, good in US_GOODS]
    rows += [Series(f"consumer_{geo.lower()}_{code.lower()}", "eurostat_panel", f"consumer:{geo}:{code}", "household",
                    "dlog", 1, "consumer", f"{country}: {good} consumer prices (Eurostat prc_hicp_minr, {code})",
                    geo=geo, item=code) for code, good in HOUSEHOLD for geo, country in HOUSEHOLD_COUNTRIES.items()]
    rows += [Series(f"world_{_slug(good)}", "worldbank", column, "world", "dlog", 1, "commodity",
                    f"{good}, {unit} (World Bank Pink Sheet)", item=WORLD_KIND.get(good, "food"))
             for column, good, unit in WORLD]
    return rows


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


def market_series() -> list[Series]:
    """The commodity runs' extra world prices (MARKETS), each with its kind of commodity as `item`."""
    return [Series(f"market_{_slug(name.split(' (')[0])}", source, code, "markets", "dlog", lag, "commodity",
                   name if source == "fao" or "EIA" in name else f"{name.split(' (')[0]} (IMF via FRED {code})",
                   item=kind) for source, code, name, kind, lag in MARKETS]


def oilflow_series() -> list[Series]:
    """The oil-flow runs' targets: each JODI_FLOWS flow in each of JODI_COUNTRIES. A flow that is
    0 (an importer's crude exports) is missing, so build_panel keeps only countries with the flow."""
    return [Series(f"oil_{group}_{product.lower()}_{iso3.lower()}", "jodi", f"{product}:{flow}:{area}", "oilflows",
                   "dlog", 2, group, f"{country}: {what}, kb/d (JODI)", geo=iso3, item=f"{product}_{flow}")
            for _, product, flow, group, what in JODI_FLOWS for area, (iso3, country) in JODI_COUNTRIES.items()]


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


def jsonstat_frame(j: dict, item: str = "nace_r2") -> pd.DataFrame:
    """A Eurostat JSON-stat payload as one column per (geo, item), one row per month. Values are
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
    return df.pivot_table(index="time", columns=["geo", item], values="value", aggfunc="first")


_INFL_SHEETS: dict[str, pd.DataFrame] = {}


def fetch_wb_inflation(code: str) -> pd.Series:
    """One country's measure from the World Bank's Global Database of Inflation (Inflation-data.xlsx,
    one sheet per measure, one column per month as yyyymm). On the energy sheet, rows noted as the
    housing and utilities index are the "ecpi_m_housing" measure and the others the energy one. A
    country with two rows of a measure (two sources) gets the one with more months since START."""
    item, iso = code.split(":")
    sheet = item.removesuffix("_housing")
    path = RAW / "worldbank_inflation.xlsx"
    if not path.exists():
        req = urllib.request.Request(INFL_PAGE, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as resp:
            page = resp.read().decode("utf-8", "ignore")
        _get(re.search(INFL_FILE, page)[0], path)
    if sheet not in _INFL_SHEETS:
        _INFL_SHEETS[sheet] = pd.read_excel(path, sheet_name=sheet)
    df = _INFL_SHEETS[sheet]
    rows = df[df["Country Code"] == iso]
    if sheet == "ecpi_m":
        housing = rows["Note"].astype(str).str.strip().str.lower().str.startswith("housing")
        rows = rows[housing if item.endswith("_housing") else ~housing]
    months = [c for c in df.columns if str(c).isdigit() and len(str(c)) == 6]
    dates = pd.to_datetime([f"{str(m)[:4]}-{str(m)[4:]}-01" for m in months])
    best = None
    for _, r in rows.iterrows():
        x = pd.Series(pd.to_numeric(r[months], errors="coerce").values, index=dates)
        x = x.where(x > 0).dropna()
        if not x.empty and (best is None or (x.loc[START:].size, x.index.max()) > (best.loc[START:].size, best.index.max())):
            best = x
    if best is None:
        raise ValueError("not published")
    return best


def fetch_fao(column: str) -> pd.Series:
    """One FAO food price index (2014-2016 = 100, monthly) from FAO's food_price_indices_data.csv."""
    path = _get(FAO_URL, RAW / "fao_food_price_indices.csv")
    df = pd.read_csv(path, skiprows=2, dtype=str)
    df = df[df["Date"].astype(str).str.fullmatch(r"\d{4}-\d{2}")]
    return pd.Series(pd.to_numeric(df[column], errors="coerce").values, index=pd.to_datetime(df["Date"] + "-01")).dropna()


_JODI: dict[str, pd.DataFrame] = {}


def jodi_frame() -> pd.DataFrame:
    """Every JODI_FLOWS flow in thousand barrels a day, all areas and months. Built once from JODI's
    yearly CSV files (primary: crude, secondary: products; about 1 GB in all, read and dropped) and
    cached as one small file."""
    path = RAW / "jodi_oil_kbd.csv"
    if "error" in _JODI:  # a failed build is not retried for every series (it downloads ~1 GB)
        raise RuntimeError(f"JODI download failed earlier: {_JODI['error']}")
    if not path.exists():
        try:
            _build_jodi(path)
        except Exception as err:
            _JODI["error"] = str(err)[:200]
            raise
    if "kbd" not in _JODI:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        df["value"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")  # "-" (none) and "x" (confidential) are missing
        df["month"] = pd.to_datetime(df["TIME_PERIOD"] + "-01")
        _JODI["kbd"] = df
    return _JODI["kbd"]


def _build_jodi(path: Path) -> None:
    """Download JODI's yearly CSV files, keep the JODI_FLOWS flows in thousand barrels a day, write path."""
    req = urllib.request.Request(JODI_PAGE, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as resp:
        page = resp.read().decode("utf-8", "ignore")
    keep = {(f, p, fl) for f, p, fl, *_ in JODI_FLOWS}
    parts = []
    for link in sorted(set(re.findall(r'/_resources/files/downloads/oil-data/annual-csv/(?:primary|secondary)/[^"]+\.csv', page))):
        kind = link.split("/")[-2]
        req = urllib.request.Request("https://www.jodidata.org" + link, headers=UA)
        with urllib.request.urlopen(req, timeout=300) as resp:
            df = pd.read_csv(io.BytesIO(resp.read()), dtype=str)
        pick = np.array([(kind, p, fl) in keep for p, fl in zip(df["ENERGY_PRODUCT"], df["FLOW_BREAKDOWN"])])
        parts.append(df[(df["UNIT_MEASURE"] == "KBD") & pick].drop(columns="UNIT_MEASURE"))
        time.sleep(0.5)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(parts).drop_duplicates(["REF_AREA", "TIME_PERIOD", "ENERGY_PRODUCT", "FLOW_BREAKDOWN"]).to_csv(path, index=False)


def fetch_jodi(code: str) -> pd.Series:
    product, flow, area = code.split(":")
    df = jodi_frame()
    x = df[(df["REF_AREA"] == area) & (df["ENERGY_PRODUCT"] == product) & (df["FLOW_BREAKDOWN"] == flow)]
    x = pd.Series(x["value"].values, index=x["month"]).sort_index()
    x = x.where(x > 0).dropna()
    if x.empty:
        raise ValueError("not published")
    return x


def oil_trade_position(start: str = "2015-01-01", end: str = "2024-12-01") -> dict[str, str]:
    """ISO3 -> "net importer" or "net exporter" of oil (crude plus products), from JODI's average
    imports minus exports over start..end; countries without all four flows are left out."""
    df = jodi_frame()
    df = df[(df["month"] >= start) & (df["month"] <= end) & df["FLOW_BREAKDOWN"].isin(["TOTIMPSB", "TOTEXPSB"])
            & df["ENERGY_PRODUCT"].isin(["TOTCRUDE", "TOTPRODS"])]
    mean = df.groupby(["REF_AREA", "ENERGY_PRODUCT", "FLOW_BREAKDOWN"])["value"].mean().unstack(["ENERGY_PRODUCT", "FLOW_BREAKDOWN"])
    out = {}
    for area, r in mean.iterrows():
        if area in JODI_COUNTRIES and r.notna().all():
            net = r[("TOTCRUDE", "TOTIMPSB")] + r[("TOTPRODS", "TOTIMPSB")] - r[("TOTCRUDE", "TOTEXPSB")] - r[("TOTPRODS", "TOTEXPSB")]
            out[JODI_COUNTRIES[area][0]] = "net importer" if net > 0 else "net exporter"
    return out


def country_classes() -> dict[str, dict]:
    """ISO3 -> iso2, name, region and income group of every World Bank economy (aggregates left out)."""
    path = _get(WB_COUNTRIES, RAW / "worldbank_countries.json")
    rows = json.loads(path.read_text(encoding="utf-8"))[1]
    return {r["id"]: {"iso2": r["iso2Code"], "name": r["name"].strip(), "region": r["region"]["value"].strip(),
                      "income": r["incomeLevel"]["value"].strip()} for r in rows if r["region"]["value"].strip() != "Aggregates"}


def iso3(geo: str, classes: dict) -> str | None:
    """A series' country as ISO 3166 alpha-3: Eurostat codes (EL, UK), alpha-2 or alpha-3."""
    if geo in classes:
        return geo
    two = {"EL": "GR", "UK": "GB"}.get(geo, geo)
    return next((k for k, v in classes.items() if v["iso2"] == two), None)


def fetch_worldbank(column: str) -> pd.Series:
    """One price from the World Bank's monthly Pink Sheet (CMO-Historical-Data-Monthly.xlsx). The
    file's address changes with every monthly update, so it is read off the commodity-markets page."""
    path = RAW / "worldbank_cmo_monthly.xlsx"
    if not path.exists():
        req = urllib.request.Request(WB_PAGE, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as resp:
            page = resp.read().decode("utf-8", "ignore")
        _get(re.search(WB_FILE, page)[0], path)
    df = pd.read_excel(path, sheet_name="Monthly Prices", header=None)
    head = [str(h).strip() for h in df.iloc[4]]
    rows = df.iloc[6:]
    rows = rows[rows[0].astype(str).str.fullmatch(r"\d{4}M\d{2}")]
    dates = pd.to_datetime(rows[0].str.replace("M", "-") + "-01")
    return pd.Series(pd.to_numeric(rows[head.index(column.strip())], errors="coerce").values, index=dates).dropna()


_PANEL_FRAMES: dict[str, pd.DataFrame] = {}


def fetch_eurostat_panel(code: str) -> pd.Series:
    """One country and industry (or good) from an EUROSTAT_PANELS dataset, which is fetched once for
    every country and item of the panel (one request per dataset). Index values <= 0 (an industry
    that stopped, e.g. Lithuanian steel, reported as 0) are missing."""
    kind, geo, item = code.split(":")
    if kind not in _PANEL_FRAMES:
        query, dim, items, tag = EUROSTAT_PANELS[kind]
        dataset, params = query.split("?")
        params += "".join(f"&{dim}={i[0]}" for i in items) + "&sinceTimePeriod=1998-01"
        path = _get(EUROSTAT.format(dataset, params), RAW / f"eurostat_{tag}_{dataset}.json")
        _PANEL_FRAMES[kind] = jsonstat_frame(json.loads(path.read_text(encoding="utf-8")), dim)
    frame = _PANEL_FRAMES[kind]
    x = frame[(geo, item)] if (geo, item) in frame else pd.Series(dtype=float)
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
         "eurostat_panel": fetch_eurostat_panel, "worldbank": fetch_worldbank, "wb_inflation": fetch_wb_inflation,
         "fao": fetch_fao, "jodi": fetch_jodi}
URLS = {"fred": "https://fred.stlouisfed.org/series/{}", "ons": "https://www.ons.gov.uk{}",
        "eurostat": "https://ec.europa.eu/eurostat/databrowser/view/{}", "portwatch": "https://portwatch.imf.org",
        "eurostat_panel": "https://ec.europa.eu/eurostat/databrowser/view/sts_inppd_m (prices), sts_inpr_m (output), "
                          "prc_hicp_minr (consumer prices)", "worldbank": WB_PAGE, "wb_inflation": INFL_PAGE,
        "fao": "https://www.fao.org/worldfoodsituation/foodpricesindex/en/", "jodi": JODI_PAGE,
        "gpr": "https://www.matteoiacoviello.com/gpr.htm", "eia": "https://www.eia.gov/petroleum/data.php",
        "ports": "https://portwatch.imf.org", "gscpi": "https://www.newyorkfed.org/research/policy/gscpi"}


# --- the panel -------------------------------------------------------------------------------

def registry(blocks=BLOCKS) -> list[Series]:
    reg = [s for s in SERIES if s.block in blocks]
    reg += industry_series() if "industry" in blocks else []
    reg += sector_series() if "sectors" in blocks else []
    reg += [s for s in goods_series() if s.block in blocks] if set(blocks) & set(GOODS_BLOCKS[1:]) else []
    reg += nation_series() if "nations" in blocks else []
    reg += oilflow_series() if "oilflows" in blocks else []
    reg += market_series() if "markets" in blocks else []
    return reg


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
        live_from = NATIONS_LIVE_FROM if s.block == "nations" else SECTOR_LIVE_FROM
        if s.block in GENERATED and (x.dropna().loc[START:].size < SECTOR_MIN_MONTHS
                                     or x.dropna().index.max() < pd.Timestamp(live_from)):
            prov.append({"series": s, "error": f"skipped: {x.dropna().loc[START:].size} months from {START[:7]}, "
                                               f"last {x.dropna().index.max():%Y-%m}"})
            continue
        if s.freq == "Q":
            x = x.resample("QS").mean()
            x.index = x.index + pd.offsets.MonthBegin(2)  # value belongs to the quarter's last month
            x = x.resample("MS").ffill()
        raw[s.key] = x
        own = [p.stat().st_mtime for p in RAW.glob(f"{s.source}_{s.code}.*")]  # its own cache file, where named by its id
        fetched = max(own) if own else min((p.stat().st_mtime for p in RAW.glob("*")), default=time.time())
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
    F, L, prov = build_panel(BLOCKS + OPTIONAL)
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
