# /// script
# requires-python = ">=3.11"
# ///
"""Gas lines for the world map: LNG shipped through Hormuz and the Gulf gas pipelines.

Writes ui/app/data/gas.json for the map, which draws these next to the yellow oil routes in another
colour. The facts and their sources are in notes/gas/lng-flows.md and notes/gas/pipelines.md.

Every number came from web search results read on 2026-10-25: EIA, IEA, IGU, GIIGNL, Kpler,
WITS and the news sites were blocked from this machine, so nothing was read on the primary page and
every value carries "verify": true. Flows are the pre-war baseline (2024 or 2025); since
28 February 2026 almost none of this LNG has moved.

    uv run experiments/gas_routes.py          # validate, write ui/app/data/gas.json, print a summary
    uv run experiments/gas_routes.py --check  # validate the written file only
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ui" / "app" / "data" / "gas.json"
ACCESSED = "2026-10-25"

# ISO 3166-1 alpha-3, all 249 officially assigned codes.
ISO3 = frozenset("""
ABW AFG AGO AIA ALA ALB AND ARE ARG ARM ASM ATA ATF ATG AUS AUT AZE BDI BEL BEN BES BFA BGD BGR BHR BHS
BIH BLM BLR BLZ BMU BOL BRA BRB BRN BTN BVT BWA CAF CAN CCK CHE CHL CHN CIV CMR COD COG COK COL COM CPV
CRI CUB CUW CXR CYM CYP CZE DEU DJI DMA DNK DOM DZA ECU EGY ERI ESH ESP EST ETH FIN FJI FLK FRA FRO FSM
GAB GBR GEO GGY GHA GIB GIN GLP GMB GNB GNQ GRC GRD GRL GTM GUF GUM GUY HKG HMD HND HRV HTI HUN IDN IMN
IND IOT IRL IRN IRQ ISL ISR ITA JAM JEY JOR JPN KAZ KEN KGZ KHM KIR KNA KOR KWT LAO LBN LBR LBY LCA LIE
LKA LSO LTU LUX LVA MAC MAF MAR MCO MDA MDG MDV MEX MHL MKD MLI MLT MMR MNE MNG MNP MOZ MRT MSR MTQ MUS
MWI MYS MYT NAM NCL NER NFK NGA NIC NIU NLD NOR NPL NRU NZL OMN PAK PAN PCN PER PHL PLW PNG POL PRI PRK
PRT PRY PSE PYF QAT REU ROU RUS RWA SAU SDN SEN SGP SGS SHN SJM SLB SLE SLV SMR SOM SPM SRB SSD STP SUR
SVK SVN SWE SWZ SXM SYC SYR TCA TCD TGO THA TJK TKL TKM TLS TON TTO TUN TUR TUV TWN TZA UGA UKR UMI URY
USA UZB VAT VCT VEN VGB VIR VNM VUT WLF WSM YEM ZAF ZMB ZWE
""".split())

# Sea lanes shared with the oil routes (ui/industry/index.html, const R), as [lng, lat].
SEGMENTS = {
    "gulf": [[56.3, 26.6], [57.2, 25.9], [58.6, 24.8], [61, 22.5]],
    "arab": [[66, 17], [73, 10], [77.5, 6.2], [81, 5.6]],
    "bay": [[88, 6], [95, 6], [98, 4.6], [100.6, 2.9], [103.6, 1.15]],
    "scs": [[105.6, 3.5], [109, 8.5], [113, 15], [117, 19.5]],
    "east": [[121.3, 22.2], [123, 25.5]],
    "red": [[58, 17], [52, 13.3], [45, 12.2], [43.3, 12.7], [40, 17], [36, 23], [33.8, 27.6], [32.6, 29.9]],
    "med": [[32.4, 31.5], [28, 33.5], [20, 35], [12, 37.3], [8, 37.8]],
    "gib": [[0, 37], [-5.6, 35.95], [-9.6, 37], [-9.8, 43], [-5.5, 48.3], [-2, 49.9], [1.5, 50.9]],
    "cape": [[60, 15], [56, 0], [46, -15], [41, -25], [33, -33], [20, -36], [12, -30]],
}

TERMINALS = {
    "QAT": {"name": "Ras Laffan", "at": [51.6, 25.9]},
    "ARE": {"name": "Das Island", "at": [52.87, 25.15]},
}

# One representative receiving terminal per buyer; most buyers have several.
# Each entry: terminal name, sea-lane segments in order, then waypoints to the terminal.
WEST_AFRICA = [[3, -10], [-12, 2], [-20, 15], [-20, 28]]       # Cape of Good Hope to the Canaries
ATLANTIC_N = [[-11.5, 38], [-9.8, 43], [-5.5, 48.3]]            # Portugal, Biscay, Ushant
TO_DOVER = [[-2, 49.9], [1.5, 50.9]]
NORTH_SEA_TO_SWINOUJSCIE = [[4.5, 53], [7.5, 57.2], [10.7, 57.9], [11.4, 56.9], [11.1, 56.2], [10.8, 55.85],
                            [10.95, 55.5], [11, 55], [11.2, 54.6], [12, 54.45], [13, 54.75], [13.6, 54.85],
                            [14, 54.4], [14.27, 53.93]]
MILFORD_HAVEN = [[-6.2, 50], [-5.3, 51.6], [-5.05, 51.7]]
ADRIATIC = [[18.9, 39.9], [16, 42.6], [13.4, 44.6], [12.6, 45.09]]
GIB_EAST = [[-11, 36], [-5.6, 35.95]]

DEST = {
    "CHN": ("Zhejiang LNG, Ningbo", ["gulf", "arab", "bay", "scs"], [[119.5, 24], [122.5, 28.5], [122, 29.9]]),
    "IND": ("Dahej", ["gulf"], [[66, 21], [70.5, 20.4], [72.3, 21], [72.55, 21.68]]),
    "KOR": ("Tongyeong", ["gulf", "arab", "bay", "scs", "east"], [[125.5, 31], [127.8, 33.6], [128.43, 34.8]]),
    "TWN": ("Yong-An, Kaohsiung", ["gulf", "arab", "bay", "scs"], [[120, 22.3], [120.2, 22.8]]),
    "PAK": ("Port Qasim", ["gulf"], [[64, 23.8], [66.9, 24.6], [67.3, 24.77]]),
    "BGD": ("Moheshkhali", ["gulf", "arab"], [[86, 10], [90, 18], [91.85, 21.55]]),
    "JPN": ("Tokyo Bay", ["gulf", "arab", "bay", "scs", "east"], [[129, 30], [134, 32.8], [139.3, 34.6], [139.8, 35.3]]),
    "THA": ("Map Ta Phut", ["gulf", "arab", "bay"], [[104.5, 4], [102.5, 9], [101.15, 12.6]]),
    "SGP": ("Jurong Island", ["gulf", "arab", "bay"], [[103.7, 1.24]]),
    "ITA": ("Adriatic LNG, Porto Viro", ["gulf", "red"], [[32.4, 31.5], [28, 33.5], [22, 35.2]] + ADRIATIC),
    "BEL": ("Zeebrugge", ["gulf", "red", "med", "gib"], [[3.2, 51.34]]),
    "POL": ("Swinoujscie", ["gulf", "red", "med", "gib"], NORTH_SEA_TO_SWINOUJSCIE),
    "GBR": ("South Hook, Milford Haven", ["gulf", "red", "med"], [[0, 37], [-5.6, 35.95], [-9.6, 37], [-9.8, 43], [-5.5, 48.3]] + MILFORD_HAVEN),
    "ESP": ("Cartagena", ["gulf", "red", "med"], [[-0.95, 37.57]]),
    "FRA": ("Fos", ["gulf", "red", "med"], [[5.5, 41.5], [4.85, 43.35]]),
}

# Round the Cape of Good Hope: QatarEnergy paused Red Sea transits in January 2024 and sent European
# cargoes round Africa, adding about nine days to an 18-day trip (gCaptain/Reuters, AA).
CAPE = {
    "ITA": WEST_AFRICA + GIB_EAST + [[0, 37], [8, 37.8], [12, 37.3], [14.5, 36.3]] + ADRIATIC,
    "BEL": WEST_AFRICA + ATLANTIC_N + TO_DOVER + [[3.2, 51.34]],
    "POL": WEST_AFRICA + ATLANTIC_N + TO_DOVER + NORTH_SEA_TO_SWINOUJSCIE,
    "GBR": WEST_AFRICA + ATLANTIC_N + MILFORD_HAVEN,
    "ESP": WEST_AFRICA + GIB_EAST + [[-2.5, 36.4], [-0.95, 37.57]],
    "FRA": WEST_AFRICA + GIB_EAST + [[0, 37], [5, 39.3], [5, 42], [4.85, 43.35]],
}
CAPE_NOTE = ("Normal lane is Suez. From January 2024 QatarEnergy paused Red Sea transits after the Houthi "
             "attacks and sent European cargoes round the Cape of Good Hope; this applied to Qatari cargoes "
             "generally, not only to this buyer.")
CAPE_SOURCE = {"source": "gCaptain (Reuters), 'Qatar reroutes LNG as more tankers avoid the Red Sea', Jan 2024; "
                         "Anadolu Agency, 'Qatar LNG vessels seem to pause gas shipments via Red Sea'",
               "url": "https://gcaptain.com/qatar-reroutes-lng-as-more-tankers-avoid-the-red-sea/"}

WITS = "https://wits.worldbank.org/trade/comtrade/en/country/{rep}/year/2024/tradeflow/{flow}/partner/{par}/product/271111"
WITS_QAT = WITS.format(rep="All", flow="Imports", par="QAT")
WITS_ARE = WITS.format(rep="All", flow="Imports", par="ARE")
WITS_SRC = "UN Comtrade via World Bank WITS, HS 271111, {who}-reported 2024 imports"
CORBEAU = ("Anne-Sophie Corbeau (Columbia CGEP) quoted by EnterpriseAM, 'Qatari LNG is trickling back "
           "through Hormuz', 15 Sep 2026")
CORBEAU_URL = ("https://enterpriseam.com/logistics/2026/09/15/qatari-lng-is-trickling-back-through-hormuz-"
               "but-the-real-divide-now-is-who-can-afford-to-keep-bidding-for-gas/")

# LNG flows through Hormuz, Mt of LNG a year. Latest full year sourced; "y2024" is a cross-check.
# (from, to, value, year, source, url, approx, extra)
FLOWS = [
    ("QAT", "CHN", 19.44, 2025, "China customs (GAC) via S&P Global; TASS gives 19.43 Mt",
     "https://www.spglobal.com/energy/en/news-research/latest-news/lng/030226-chinese-lng-traders-eye-strait-of-hormuz-for-potential-supply-disruption-risks",
     False, {"y2024": {"value": 18.34, "source": WITS_SRC.format(who="China"), "url": WITS_QAT}}),
    ("QAT", "IND", 11.3, 2024, WITS_SRC.format(who="India"), WITS.format(rep="IND", flow="Imports", par="ALL"),
     False, {"note": "No clean calendar-2025 figure found; S&P puts 2025 at over 40% of more than 25 Mt."}),
    ("QAT", "TWN", 8.14, 2025, "Taiwan customs via LNG Prime, 'Taiwan boosts LNG imports in 2025'",
     "https://lngprime.com/lng-terminals/taiwan-boosts-lng-imports-in-2025/173997/",
     False, {"y2024": {"value": 5.4, "source": "Taiwan customs via LNG Prime",
                       "url": "https://lngprime.com/lng-terminals/taiwan-boosts-lng-imports-in-2025/173997/"}}),
    ("QAT", "KOR", 6.97, 2025, "Korea Customs Service via S&P Global (Hellenic Shipping News reprint); Kpler gives 7.16 Mt",
     "https://www.hellenicshippingnews.com/u-s-lng-fills-qatar-gap-as-south-korea-shifts-imports-and-boosts-profits/",
     False, {"y2024": {"value": 8.88, "source": WITS_SRC.format(who="Korea"), "url": WITS_QAT}}),
    ("QAT", "PAK", 6.57, 2025, "S&P Global Commodity Insights (CERA data): 6.57 of 6.63 Mt imported",
     "https://www.spglobal.com/energy/en/news-research/latest-news/lng/042426-pakistan-receives-four-bids-for-upcoming-delivery-of-three-spot-lng-cargoes",
     False, {"y2024": {"value": 6.66, "source": WITS_SRC.format(who="Pakistan"), "url": WITS_QAT}}),
    ("QAT", "ITA", 4.8, 2025, CORBEAU, CORBEAU_URL,
     True, {"y2024": {"value": 4.75, "source": WITS_SRC.format(who="Italy"), "url": WITS_QAT}}),
    ("QAT", "BGD", 4.15, 2025, "Egypt Oil & Gas, 'QatarEnergy cuts LNG deliveries to Bangladesh' (of nearly 7 Mt imported)",
     "https://egyptoil-gas.com/news/qatarenergy-cuts-lng-deliveries-to-bangladesh/", True, {}),
    ("QAT", "JPN", 2.87, 2024, "Japan Ministry of Finance via AGBI; UN Comtrade via WITS gives the same",
     "https://www.agbi.com/oil-and-gas/2025/05/lng-qatar-japan-sales/", False, {}),
    ("QAT", "THA", 2.2, 2024, WITS_SRC.format(who="Thailand"), WITS.format(rep="THA", flow="Imports", par="ALL"), False, {}),
    ("QAT", "BEL", 1.7, 2025, CORBEAU, CORBEAU_URL,
     True, {"y2024": {"value": 1.88, "source": WITS_SRC.format(who="Belgium"), "url": WITS_QAT}}),
    ("QAT", "SGP", 1.69, 2024, WITS_SRC.format(who="Singapore"), WITS.format(rep="SGP", flow="Imports", par="ALL"),
     False, {"note": "Qatar's own records show 5.06 Mt to Singapore; the gap is usual for a trading hub."}),
    ("QAT", "POL", 1.6, 2025, CORBEAU, CORBEAU_URL,
     True, {"y2024": {"value": 1.75, "source": "UN Comtrade via World Bank WITS, HS 271111, exporter-reported 2024",
                      "url": WITS.format(rep="All", flow="Exports", par="POL")}}),
    ("QAT", "ESP", 0.64, 2024, WITS_SRC.format(who="Spain"), WITS_QAT, False, {}),
    ("QAT", "GBR", 0.58, 2024, WITS_SRC.format(who="UK"), WITS.format(rep="GBR", flow="Imports", par="ALL"),
     False, {"note": "Statista gives 8.6 TWh for 2024, about the same tonnage."}),
    ("QAT", "FRA", 0.26, 2024, WITS_SRC.format(who="France"), WITS_QAT, False, {}),
    ("ARE", "IND", 3.16, 2024, WITS_SRC.format(who="India"), WITS_ARE, False, {}),
    ("ARE", "JPN", 0.96, 2024, WITS_SRC.format(who="Japan"), WITS_ARE, False, {}),
    ("ARE", "CHN", 0.85, 2024, WITS_SRC.format(who="China"), WITS_ARE, False, {}),
    ("ARE", "TWN", 0.47, 2024, WITS_SRC.format(who="Taiwan") + " (listed as 'Other Asia, nes')", WITS_ARE, False, {}),
    ("ARE", "KOR", 0.42, 2024, WITS_SRC.format(who="Korea"), WITS_ARE, False, {}),
]

# Buyers asked about but left off the map, and why.
EXCLUDED = [
    {"from": "QAT", "to": "KWT", "reason": "Al-Zour is inside the Gulf, so these cargoes never pass Hormuz. "
     "Contracts are 3 Mtpa from 2022 plus 3 Mtpa from 2025; no actual 2024 or 2025 tonnage found.",
     "url": "https://www.offshore-technology.com/news/qatarenergy-kuwait-petroleum-lng-supply/"},
    {"from": "QAT", "to": "EGY", "reason": "Egypt imported 9.01 Mt in 2025, 90.9% from the US; no Qatari tonnage found. "
     "QatarEnergy agreed to supply Sokhna and Damietta in January 2026.",
     "url": "https://www.spglobal.com/energy/en/news-research/latest-news/lng/011426-egypts-2025-lng-imports-hit-record-high-as-energy-appetite-grows"},
    {"from": "QAT", "to": "TUR", "reason": "No Qatari tonnage found for 2024 or 2025.", "url": WITS_QAT},
    {"from": "QAT", "to": "NLD", "reason": "No Qatari tonnage found for 2024 or 2025.", "url": WITS_QAT},
    {"from": "QAT", "to": "DEU", "reason": "No Qatari tonnage found for 2024 or 2025.", "url": WITS_QAT},
]

OUTSIDE_STRAIT = [{
    "name": "Oman LNG, Qalhat (near Sur)", "iso3": "OMN", "at": [59.37, 22.7], "approx": True,
    "note": "Loads on the Gulf of Oman coast, outside the strait, so it kept shipping in 2026. "
            "Nameplate 10.4 Mtpa (IGU), raised to 11.5 Mtpa (Oman Observer).",
    "exports": {"value": 11.9, "unit": "Mt", "year": 2025, "source": "IGU World LNG Report 2026 via Oman Observer",
                "url": "https://www.omanobserver.om/article/1192704/business/oman-lng-exports-reach-119-million-tonnes"},
}]

# Pipelines in and around the Gulf that matter if Hormuz closes. Paths are a handful of waypoints.
PIPELINES = [
    {"name": "Dolphin (Ras Laffan to Taweelah)", "from": "QAT", "to": "ARE", "capacity": 3.2, "unit": "bcf/d",
     "year": 2007, "length_km": 364, "diameter_in": 48, "status": "operating",
     "flow": {"value": 2.0, "unit": "bcf/d", "basis": "contracted, typical delivery",
              "source": "Gulf News, 'Dolphin Energy is to raise gas flow to UAE'",
              "url": "https://gulfnews.com/business/energy/dolphin-energy-is-to-raise-gas-flow-to-uae-1.623037"},
     "source": "Offshore Technology, Dolphin Gas Project (design capacity); Dolphin Energy operations page",
     "url": "https://www.offshore-technology.com/projects/dolphin-gas/", "bypasses_hormuz": True,
     "note": "Subsea and wholly inside the Gulf: Qatari gas reaches the UAE and Oman without the strait, "
             "but the line is exposed to attacks inside the Gulf.",
     "path": [[51.6, 25.9], [52.4, 25.55], [53.4, 25.15], [54.2, 24.9], [54.69, 24.77]]},
    {"name": "Dolphin Taweelah-Fujairah", "from": "ARE", "to": "ARE", "capacity": 1.6, "unit": "bcf/d",
     "year": 2010, "length_km": 244, "diameter_in": 48, "status": "operating",
     "source": "Gulf News, 'Dolphin Energy completes Taweelah-Fujairah pipeline'; MEED",
     "url": "https://gulfnews.com/business/energy/dolphin-energy-completes-taweelah---fujairah-pipeline-1.720870",
     "bypasses_hormuz": True,
     "note": "Carries Qatari gas across the UAE to Fujairah's power plants on the Gulf of Oman coast. "
             "Year is approximate.",
     "path": [[54.69, 24.77], [55.2, 24.85], [55.75, 25], [56.1, 25.2], [56.35, 25.3]]},
    {"name": "Dolphin to Oman (Al Ain to Sohar)", "from": "ARE", "to": "OMN", "capacity": 200, "unit": "MMscf/d",
     "year": 2008, "status": "operating",
     "source": "Oil & Gas Journal, 'Dolphin Energy begins supplying gas to Oman' (25-year contract from 2005)",
     "url": "https://www.ogj.com/pipelines-transportation/article/17267973/dolphin-energy-begins-supplying-gas-to-oman",
     "bypasses_hormuz": True,
     "note": "Capacity is the contracted volume. Gas runs through Dolphin's eastern system to Al Ain, "
             "then Oman's line from Al Buraimi to Sohar.",
     "path": [[54.69, 24.77], [55.2, 24.5], [55.76, 24.22], [56.3, 24.35], [56.74, 24.36]]},
    {"name": "Iran-Turkey (Tabriz to Ankara)", "from": "IRN", "to": "TUR", "capacity": 14, "unit": "bcm/y",
     "year": 2001, "length_km": 2577, "status": "operating; contract reported expired 29 Jul 2026",
     "flow": {"value": 7.81, "unit": "bcm/y", "year": 2025, "basis": "imports, 13.5% of Turkey's gas imports",
              "source": "MEES, 'Turkey open to Iran gas contract extension', 24 Apr 2026",
              "url": "https://www.mees.com/2026/4/24/news-in-brief/turkey-open-to-iran-gas-contract-extension/8161dba0-3fcb-11f1-a220-af3d2a70a45d"},
     "contract": {"value": 9.6, "unit": "bcm/y", "source": "The New Arab (Reuters)",
                  "url": "https://www.newarab.com/news/turkey-says-iran-gas-pipeline-contract-nearing-expiry"},
     "source": "Global Energy Monitor, Tabriz-Ankara Pipeline", "url": "https://gem.wiki/Tabriz-Ankara_Pipeline",
     "bypasses_hormuz": True,
     "note": "Overland. One outlet reports the 25-year contract lapsed on 29 July 2026 with flows continuing "
             "on temporary terms; not confirmed elsewhere.",
     "path": [[46.29, 38.08], [44.39, 39.39], [44.08, 39.55], [41.27, 39.9], [39.49, 39.75], [37.02, 39.75],
              [35.48, 38.72], [32.85, 39.93]]},
    {"name": "Iran-Iraq (Naft Shahr to Baghdad)", "from": "IRN", "to": "IRQ", "capacity": 25, "unit": "mcm/d",
     "year": 2017, "status": "operating, cut in 2026",
     "flow": {"value": 15, "unit": "mcm/d", "year": 2026, "basis": "upper bound, April 2026, Iraq total",
              "source": "S&P Global, 'Iraq faces critical gas shortage as Middle East war cuts vital imports'",
              "url": "https://www.spglobal.com/energy/en/news-research/latest-news/shipping/042726-iraq-faces-critical-gas-shortage-as-middle-east-war-cuts-vital-imports"},
     "contract": {"value": 50, "unit": "mcm/d", "basis": "Iraq's whole contract, renewed 2024",
                  "source": "S&P Global",
                  "url": "https://www.spglobal.com/energy/en/news-research/latest-news/shipping/042726-iraq-faces-critical-gas-shortage-as-middle-east-war-cuts-vital-imports"},
     "source": "Argus, 'Iraq insecurity delays Iran gas project' (up to 25 mcm/d for three Baghdad plants)",
     "url": "https://www.argusmedia.com/en/news-and-insights/latest-market-news/927476-iraq-insecurity-delays-iran-gas-project",
     "bypasses_hormuz": True,
     "note": "Overland. Feeds Baghdad-area power plants (Mansuriya, Quds, Baghdad, Bismaya). Year is approximate.",
     "path": [[46.4, 33.75], [45.9, 33.95], [45.5, 34], [45, 34.05], [44.6, 33.55], [44.4, 33.3]]},
    {"name": "Iran-Iraq (Shalamcheh to Basra)", "from": "IRN", "to": "IRQ", "capacity": 25, "unit": "mcm/d",
     "year": 2017, "length_km": 141, "diameter_in": 48, "status": "built; steady flows not confirmed",
     "source": "Shana (Iran oil ministry news), Shalamcheh terminal maximum 25 mcm/d to Basra",
     "url": "https://en.shana.ir/news/280695/Shana", "bypasses_hormuz": True,
     "note": "Overland branch of IGAT-6 via Ahvaz and Khorramshahr. Sources found date from 2015 to 2018; "
             "none confirms regular flows since. Year is approximate.",
     "path": [[48.68, 31.32], [48.25, 30.6], [47.98, 30.5], [47.75, 30.5]]},
    {"name": "Iran-Pakistan (IP, unfinished)", "from": "IRN", "to": "PAK", "capacity": 750, "unit": "MMcf/d",
     "year": 2024, "status": "Iranian section built; Pakistani section (about 781 km) not built; no gas has flowed",
     "source": "World Pipelines, 'First phase of Iran-Pakistan gas pipeline approved', Feb 2024 (design capacity)",
     "url": "https://www.worldpipelines.com/business-news/27022024/first-phase-of-iran-pakistan-gas-pipeline-approved/",
     "bypasses_hormuz": True,
     "note": "Would give Pakistan, which takes 99% of its LNG from the Gulf, gas without the strait. "
             "path is the built Iranian side; planned_path is the Pakistani side to Nawabshah.",
     "path": [[52.61, 27.48], [54.5, 27.3], [56.4, 27.4], [58.3, 27.4], [60.68, 27.2], [61.6, 25.3]],
     "planned_path": [[61.6, 25.3], [62.33, 25.13], [63.47, 25.26], [64.64, 25.21], [66.5, 25.5], [68.41, 26.25]]},
]
PIPELINES_LEFT_OUT = ("Arab Gas Pipeline (Egypt to Jordan, Syria, Lebanon): carries Egyptian and Israeli gas, "
                      "not Gulf gas, so a Hormuz closure does not change it. Saudi Arabia's Master Gas System is "
                      "domestic only.")

EIA = ("EIA, 'About one-fifth of global LNG trade flows through the Strait of Hormuz', 24 Jun 2025",
       "https://www.eia.gov/todayinenergy/detail.php?id=65584")
IEA_FS = ("IEA, Strait of Hormuz factsheet, Feb 2026",
          "https://iea.blob.core.windows.net/assets/c8248eba-8689-46d9-ae4b-b858b59c0f1c/StraitofHormuz2026-Factsheet.pdf")
FACTS = [
    ("Share of world LNG trade through Hormuz", 20, "%", 2024, *EIA, True),
    ("Qatar LNG through Hormuz", 9.3, "bcf/d", 2024, *EIA, True),
    ("UAE LNG through Hormuz", 0.7, "bcf/d", 2024, *EIA, True),
    ("Share of Hormuz LNG going to Asia", 83, "%", 2024, *EIA, False),
    ("LNG through Hormuz", 110, "bcm", 2025, "IEA, Strait of Hormuz page ('over 110 bcm')",
     "https://www.iea.org/about/oil-security-and-emergency-response/strait-of-hormuz", True),
    ("Share of world LNG trade through Hormuz", 20, "%", 2025, *IEA_FS, True),
    ("Share of Hormuz LNG going to Asia", 90, "%", 2025, *IEA_FS, True),
    ("Qatar LNG exports", 81.5, "Mt", 2025, "IGU World LNG Report 2026 via The Peninsula",
     "https://thepeninsulaqatar.com/article/30/07/2026/qatar-strengthens-lng-leadership-as-exports-reach-record-high-in-2025", False),
    ("Qatar LNG exports", 77.23, "Mt", 2024, "IGU World LNG Report 2025 via SAFETY4SEA",
     "https://safety4sea.com/igu-world-lng-report-lng-trade-grew-by-2-4-in-2024/", False),
    ("UAE LNG exports", 7, "bcm", 2025, *IEA_FS, True),
    ("World LNG trade", 436.98, "Mt", 2025, "IGU World LNG Report 2026 via Oil & Gas Journal",
     "https://www.ogj.com/general-interest/economics-markets/news/55392446/global-lng-trade-hits-record-in-2025-as-2026-tests-market-resilience", False),
    ("World LNG trade", 411.24, "Mt", 2024, "IGU World LNG Report 2025 via IIR",
     "https://iifiir.org/en/news/world-lng-report-2025-lng-trade-continues-to-grow-requiring-increased-global-decarbonisation-efforts", False),
    ("Qatar LNG to the EU and UK", 9.2, "Mt", 2025, "Kpler, 'Middle East conflict: gas market implications'",
     "https://www.kpler.com/blog/middle-east-conflict---gas-market-implications-a-continuing-assessment", False),
    ("Qatar LNG capacity lost to the 2026 strikes (trains 4 and 6)", 12.8, "Mtpa", 2026, "GIIGNL Annual Report 2026",
     "https://giignl-documents.s3.fr-par.scw.cloud/public/giignl-2026-annual-report.pdf", False),
]

NOTE = ("Pre-war baseline: each flow is the latest full year found (2024 or 2025), Mt of LNG a year. "
        "Values are customs data or analyst estimates read from web search results on 2026-10-25, so each "
        "has verify: true; approx: true marks rounded estimates. Routes reuse the oil sea lanes plus a few "
        "waypoints to one representative terminal per buyer, so every line is approximate, as are all "
        "pipeline paths. Hormuz LNG has mostly stopped since 28 February 2026.")

# Unit conversions to bcm a year, for drawing pipeline widths on one scale.
TO_BCM_Y = {"bcm/y": 1.0, "bcf/d": 0.0283168 * 365, "MMscf/d": 0.0283168 * 365 / 1000,
            "MMcf/d": 0.0283168 * 365 / 1000, "mcm/d": 0.365}


def expand(start: list, segments: list[str], end: list) -> list:
    """Full polyline: loading terminal, the named sea lanes in order, then the waypoints to the buyer."""
    pts = [start]
    for name in segments:
        pts += SEGMENTS[name]
    return pts + end


def route(origin: str, segments: list[str], end: list) -> dict:
    start = TERMINALS[origin]["at"]
    return {"start": start, "segments": segments, "end": end, "path": expand(start, segments, end)}


def build(today: str | None = None) -> dict:
    lng = []
    for frm, to, value, year, source, url, approx, extra in FLOWS:
        terminal, segs, end = DEST[to]
        flow = {"from": frm, "to": to, "value": value, "unit": "Mt", "year": year, "source": source, "url": url,
                "approx": approx, "verify": True, "accessed": ACCESSED, "via": "hormuz",
                "from_terminal": TERMINALS[frm]["name"], "to_terminal": terminal, "route": route(frm, segs, end)}
        if to in CAPE:
            flow["alt_route"] = {**route(frm, ["gulf", "cape"], CAPE[to]), "used": "2024-2025",
                                 "note": CAPE_NOTE, **CAPE_SOURCE}
        flow.update(extra)
        lng.append(flow)
    pipelines = []
    for p in PIPELINES:
        q = {**p, "capacity_bcm_y": round(p["capacity"] * TO_BCM_Y[p["unit"]], 1), "approx": True,
             "verify": True, "accessed": ACCESSED}
        pipelines.append(q)
    facts = [{"label": label, "value": value, "unit": unit, "year": year, "source": source, "url": url,
              "approx": approx, "verify": True, "accessed": ACCESSED}
             for label, value, unit, year, source, url, approx in FACTS]
    return {
        "generated": today or datetime.now(UTC).date().isoformat(),
        "note": NOTE,
        "terminals": TERMINALS,
        "segments": SEGMENTS,
        "lng": lng,
        "excluded": EXCLUDED,
        "outside_strait": OUTSIDE_STRAIT,
        "pipelines": pipelines,
        "pipelines_left_out": PIPELINES_LEFT_OUT,
        "facts": facts,
    }


# ------------------------------------------------------------------------------------- validation
def _point_ok(p) -> bool:
    return (isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                       for v in p)
            and -180 <= p[0] <= 180 and -90 <= p[1] <= 90)


def _sourced(obj: dict, where: str) -> list[str]:
    errs = []
    v = obj.get("value", obj.get("capacity"))
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
        errs.append(f"{where}: value must be a positive number, got {v!r}")
    if not str(obj.get("source", "")).strip():
        errs.append(f"{where}: missing source")
    if not str(obj.get("url", "")).startswith("https://"):
        errs.append(f"{where}: url must start with https://")
    return errs


def _points(pts, where: str, max_step: float = 25.0) -> list[str]:
    if not isinstance(pts, list) or len(pts) < 1:
        return [f"{where}: no points"]
    errs = [f"{where}[{i}]: bad lng/lat {p!r}" for i, p in enumerate(pts) if not _point_ok(p)]
    if not errs:  # a long jump between neighbours usually means a typo or swapped lng/lat
        for i in range(1, len(pts)):
            step = ((pts[i][0] - pts[i - 1][0]) ** 2 + (pts[i][1] - pts[i - 1][1]) ** 2) ** 0.5
            if step > max_step:
                errs.append(f"{where}: jump of {step:.1f} degrees at point {i}")
    return errs


def _route(r: dict, where: str, origin: str) -> list[str]:
    errs = [f"{where}: unknown segment {s!r}" for s in r.get("segments", []) if s not in SEGMENTS]
    if errs:
        return errs
    if r.get("start") != TERMINALS.get(origin, {}).get("at"):
        errs.append(f"{where}: start is not the {origin} loading terminal")
    if not r.get("segments") or r["segments"][0] != "gulf":
        errs.append(f"{where}: a Hormuz route must begin with the gulf segment")
    errs += _points(r.get("end"), f"{where}.end")
    if r.get("path") != expand(r.get("start"), r.get("segments", []), r.get("end", [])):
        errs.append(f"{where}: path does not match start + segments + end")
    return errs + _points(r.get("path"), f"{where}.path")


def validate(data: dict) -> list[str]:
    errs = []
    for key in ("generated", "note", "lng", "pipelines", "facts"):
        if key not in data:
            errs.append(f"missing top-level key {key!r}")
    try:
        date.fromisoformat(str(data.get("generated")))
    except ValueError:
        errs.append("generated is not an ISO date")
    seen = set()
    for f in data.get("lng", []):
        where = f"lng {f.get('from')}->{f.get('to')}"
        for k in ("from", "to"):
            if f.get(k) not in ISO3:
                errs.append(f"{where}: {k} {f.get(k)!r} is not an ISO 3166-1 alpha-3 code")
        if (f.get("from"), f.get("to")) in seen:
            errs.append(f"{where}: duplicate flow")
        seen.add((f.get("from"), f.get("to")))
        errs += _sourced(f, where)
        if f.get("unit") != "Mt":
            errs.append(f"{where}: unit must be Mt")
        if not isinstance(f.get("year"), int) or not 2015 <= f["year"] <= 2026:
            errs.append(f"{where}: bad year {f.get('year')!r}")
        if not isinstance(f.get("approx"), bool):
            errs.append(f"{where}: approx must be true or false")
        if f.get("via") != "hormuz":
            errs.append(f"{where}: via must be 'hormuz'")
        errs += _route(f.get("route", {}), f"{where} route", f.get("from"))
        if "alt_route" in f:
            errs += _route(f["alt_route"], f"{where} alt_route", f.get("from"))
            if "cape" not in f["alt_route"].get("segments", []):
                errs.append(f"{where}: alt_route should go round the Cape")
        if "y2024" in f:
            errs += _sourced(f["y2024"], f"{where} y2024")
    for p in data.get("pipelines", []):
        where = f"pipeline {p.get('name')}"
        for k in ("from", "to"):
            if p.get(k) not in ISO3:
                errs.append(f"{where}: {k} {p.get(k)!r} is not an ISO 3166-1 alpha-3 code")
        errs += _sourced(p, where)
        if p.get("unit") not in TO_BCM_Y:
            errs.append(f"{where}: unknown unit {p.get('unit')!r}")
        for k in ("flow", "contract"):
            if k in p:
                errs += _sourced(p[k], f"{where} {k}")
        if not isinstance(p.get("bypasses_hormuz"), bool):
            errs.append(f"{where}: bypasses_hormuz must be true or false")
        if not str(p.get("status", "")).strip():
            errs.append(f"{where}: missing status")
        if not isinstance(p.get("year"), int):
            errs.append(f"{where}: missing year")
        if len(p.get("path", [])) < 2:
            errs.append(f"{where}: path needs at least two points")
        errs += _points(p.get("path"), f"{where}.path")
        if "planned_path" in p:
            errs += _points(p["planned_path"], f"{where}.planned_path")
    for i, fct in enumerate(data.get("facts", [])):
        where = f"fact {fct.get('label', i)} ({fct.get('year')})"
        errs += _sourced(fct, where)
        if not str(fct.get("unit", "")).strip() or not isinstance(fct.get("year"), int):
            errs.append(f"{where}: needs unit and year")
    for o in data.get("outside_strait", []):
        if o.get("iso3") not in ISO3:
            errs.append(f"outside_strait {o.get('name')}: bad iso3")
        if not _point_ok(o.get("at")):
            errs.append(f"outside_strait {o.get('name')}: bad point")
        errs += _sourced(o.get("exports", {}), f"outside_strait {o.get('name')}")
    for t, term in data.get("terminals", {}).items():
        if t not in ISO3 or not _point_ok(term.get("at")):
            errs.append(f"terminal {t}: bad code or point")
    return errs


# ------------------------------------------------------------------------------------------ output
def dumps(data: dict) -> str:
    text = json.dumps(data, indent=1, ensure_ascii=False)
    # keep each [lng, lat] pair on one line
    return re.sub(r"\[\s*(-?[\d.]+),\s*(-?[\d.]+)\s*\]", r"[\1, \2]", text) + "\n"


def summary(data: dict) -> None:
    rows = sorted(data["lng"], key=lambda f: (f["from"], -f["value"]))
    print(f"{'from':4} {'to':4} {'Mt':>6} {'year':4}  {'approx':6}  {'Cape alt':8}  source")
    for f in rows:
        print(f"{f['from']:4} {f['to']:4} {f['value']:6.2f} {f['year']:4}  {'yes' if f['approx'] else '':6}  "
              f"{'yes' if 'alt_route' in f else '':8}  {f['source'][:70]}")
    exports = {(x["label"], x["year"]): x["value"] for x in data["facts"]}
    for iso, label in (("QAT", "Qatar LNG exports"),):
        total = sum(f["value"] for f in rows if f["from"] == iso)
        ref = exports.get((label, 2025))
        print(f"\n{iso} flows drawn: {total:.1f} Mt (mixed 2024/2025) against {ref} Mt exported in 2025"
              f" ({total / ref:.0%})")
    are = sum(f["value"] for f in rows if f["from"] == "ARE")
    print(f"ARE flows drawn: {are:.1f} Mt (2024); UAE exported about 7 bcm in 2025")
    print(f"\n{'pipeline':36} {'capacity':>16} {'bcm/y':>6}  bypass  status")
    for p in data["pipelines"]:
        cap = f"{p['capacity']:g} {p['unit']}"
        print(f"{p['name'][:36]:36} {cap:>16} {p['capacity_bcm_y']:6.1f}  {'yes' if p['bypasses_hormuz'] else 'no':6}  "
              f"{p['status'][:40]}")
    print(f"\n{'fact':58} {'value':>8} {'unit':5} year")
    for x in data["facts"]:
        print(f"{x['label'][:58]:58} {x['value']:>8g} {x['unit']:5} {x['year']}")
    print(f"\nLeft out: {', '.join(e['from'] + '->' + e['to'] for e in data['excluded'])}")


def main(argv: list[str]) -> int:
    if "--check" in argv:
        data = json.loads(OUT.read_text())
    else:
        data = build()
    errs = validate(data)
    if errs:
        print("gas.json failed validation:", *errs, sep="\n  ")
        return 1
    if "--check" not in argv:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(dumps(data))
        print(f"wrote {OUT.relative_to(ROOT)}: {len(data['lng'])} LNG flows, {len(data['pipelines'])} pipelines, "
              f"{len(data['facts'])} facts\n")
    summary(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
