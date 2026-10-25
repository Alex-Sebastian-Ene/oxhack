# LNG through Hormuz: flows by buyer (research desk, 25 Oct 2026)

Data for the map's gas lines: `experiments/gas_routes.py` writes `ui/app/data/gas.json`.
Pipelines are in `pipelines.md`.

**How collected:** web search on 25 Oct 2026. EIA, IEA, IGU, GIIGNL, Kpler, WITS and the news sites were
all blocked from this machine (proxy refused the connection), so **every figure is from search-result
snippets** and carries `"verify": true` in the JSON. All URLs below were accessed 25 Oct 2026.

**What the numbers are:** Mt of LNG a year, the pre-war baseline. Each flow uses the latest full year
found (2025 where sourced, else 2024). Since 28 Feb 2026 almost none of this has moved.

## Qatar (Ras Laffan) and UAE (Das Island)

Both terminals are inside the Gulf, so everything they ship to buyers outside it passes Hormuz.

| From | To | Mt | Year | Source | Cross-check |
|---|---|---|---|---|---|
| QAT | China | 19.44 | 2025 | China customs via [S&P Global](https://www.spglobal.com/energy/en/news-research/latest-news/lng/030226-chinese-lng-traders-eye-strait-of-hormuz-for-potential-supply-disruption-risks); [TASS](https://tass.com/economy/2073441/amp) gives 19.43 | 18.34 in 2024 (WITS) |
| QAT | India | 11.30 | 2024 | UN Comtrade via [WITS](https://wits.worldbank.org/trade/comtrade/en/country/IND/year/2024/tradeflow/Imports/partner/ALL/product/271111) | 2025 calendar not found cleanly |
| QAT | Taiwan | 8.14 | 2025 | Taiwan customs via [LNG Prime](https://lngprime.com/lng-terminals/taiwan-boosts-lng-imports-in-2025/173997/) | 5.4 in 2024, same source |
| QAT | South Korea | 6.97 | 2025 | Korea Customs via [S&P Global / Hellenic Shipping News](https://www.hellenicshippingnews.com/u-s-lng-fills-qatar-gap-as-south-korea-shifts-imports-and-boosts-profits/); Kpler 7.16 | 8.88 in 2024 (WITS) |
| QAT | Pakistan | 6.57 | 2025 | [S&P Global](https://www.spglobal.com/energy/en/news-research/latest-news/lng/042426-pakistan-receives-four-bids-for-upcoming-delivery-of-three-spot-lng-cargoes) (6.57 of 6.63 Mt) | 6.66 in 2024 (WITS) |
| QAT | Italy | 4.8 (approx) | 2025 | A-S Corbeau via [EnterpriseAM](https://enterpriseam.com/logistics/2026/09/15/qatari-lng-is-trickling-back-through-hormuz-but-the-real-divide-now-is-who-can-afford-to-keep-bidding-for-gas/) | 4.75 in 2024 (WITS) |
| QAT | Bangladesh | 4.15 (approx) | 2025 | [Egypt Oil & Gas](https://egyptoil-gas.com/news/qatarenergy-cuts-lng-deliveries-to-bangladesh/) (of nearly 7 Mt) | single source |
| QAT | Japan | 2.87 | 2024 | Japan MoF via [AGBI](https://www.agbi.com/oil-and-gas/2025/05/lng-qatar-japan-sales/) | WITS agrees |
| QAT | Thailand | 2.20 | 2024 | UN Comtrade via [WITS](https://wits.worldbank.org/trade/comtrade/en/country/THA/year/2024/tradeflow/Imports/partner/ALL/product/271111) | |
| QAT | Belgium | 1.7 (approx) | 2025 | Corbeau via EnterpriseAM (above) | 1.88 in 2024 (WITS) |
| QAT | Singapore | 1.69 | 2024 | UN Comtrade via [WITS](https://wits.worldbank.org/trade/comtrade/en/country/SGP/year/2024/tradeflow/Imports/partner/ALL/product/271111) | Qatar's own records: 5.06 Mt |
| QAT | Poland | 1.6 (approx) | 2025 | Corbeau via EnterpriseAM (above) | 1.75 in 2024 (WITS, exporter side) |
| QAT | Spain | 0.64 | 2024 | UN Comtrade via [WITS, imports from Qatar](https://wits.worldbank.org/trade/comtrade/en/country/All/year/2024/tradeflow/Imports/partner/QAT/product/271111) | |
| QAT | UK | 0.58 | 2024 | UN Comtrade via [WITS](https://wits.worldbank.org/trade/comtrade/en/country/GBR/year/2024/tradeflow/Imports/partner/ALL/product/271111) | Statista: 8.6 TWh, similar |
| QAT | France | 0.26 | 2024 | WITS, imports from Qatar (above) | |
| ARE | India | 3.16 | 2024 | UN Comtrade via [WITS, imports from UAE](https://wits.worldbank.org/trade/comtrade/en/country/All/year/2024/tradeflow/Imports/partner/ARE/product/271111) | |
| ARE | Japan | 0.96 | 2024 | same | |
| ARE | China | 0.85 | 2024 | same | |
| ARE | Taiwan | 0.47 | 2024 | same ("Other Asia, nes") | |
| ARE | South Korea | 0.42 | 2024 | same | |

Coverage: the Qatari flows add up to 72.9 Mt (mixed years) against 81.5 Mt exported in 2025, about 89%.
The UAE flows add up to 5.9 Mt (2024); the UAE exported about 7 bcm in 2025 (IEA).

Notes on the numbers:
- WITS figures are importer-reported customs quantities (HS 271111), except Poland's 2024 cross-check,
  which is exporter-reported.
- The three EU figures for 2025 are one analyst's rounded estimates (Columbia CGEP), so they are marked
  approximate. Kpler puts all Qatari LNG to the EU and UK in 2025 at 9.2 Mt, which leaves about 1.1 Mt for
  the UK, France, Spain and the rest.
- Bangladesh's figure comes from a single outlet quoting officials ("around 4.15 Mt").

## Left off the map

- **Kuwait:** Al-Zour is inside the Gulf, so Qatari cargoes never pass Hormuz. Contracts are 3 Mtpa from 2022
  plus 3 Mtpa from Jan 2025 ([Offshore Technology](https://www.offshore-technology.com/news/qatarenergy-kuwait-petroleum-lng-supply/)).
  Energy Aspects counts 7.35 Mt of imports from Mar 2025 to Feb 2026, "the vast majority" Qatari, but no
  Qatari tonnage was found. Kuwait's other suppliers (Oman, Nigeria) do have to pass the strait.
- **Egypt:** imported 9.01 Mt in 2025, 90.9% from the US
  ([S&P Global](https://www.spglobal.com/energy/en/news-research/latest-news/lng/011426-egypts-2025-lng-imports-hit-record-high-as-energy-appetite-grows));
  QatarEnergy only agreed to supply Sokhna and Damietta in Jan 2026.
- **Turkey, Netherlands, Germany:** no Qatari tonnage found for 2024 or 2025.

## Routes

- Each route reuses the oil map's named sea lanes (`gulf`, `arab`, `bay`, `scs`, `east`, `red`, `med`,
  `gib`, `cape`), then a few waypoints to one representative terminal per buyer (for example Dahej for
  India, Tongyeong for Korea, Adriatic LNG for Italy, Zeebrugge, Swinoujscie, South Hook). Most buyers
  have several terminals, so every line is approximate. The JSON also carries the expanded `path`.
- **Red Sea:** in January 2024 QatarEnergy paused Red Sea transits after the Houthi attacks and sent
  European cargoes round the Cape of Good Hope, adding about nine days to an 18-day trip
  ([gCaptain/Reuters](https://gcaptain.com/qatar-reroutes-lng-as-more-tankers-avoid-the-red-sea/),
  [Anadolu](https://www.aa.com.tr/en/energy/finance/qatar-lng-vessels-seem-to-pause-gas-shipments-via-red-sea/40232)).
  Bloomberg called a Qatari tanker's Red Sea voyage to Poland in Oct 2026 "rare". So every Europe-bound
  flow has `route` via Suez (the normal lane) and `alt_route` round the Cape (used 2024-2025). The sources
  describe Qatari cargoes in general, not each buyer.

## Outside the strait: Oman LNG

Oman LNG loads at Qalhat near Sur, on the Gulf of Oman coast, so it does not need Hormuz. It exported
11.9 Mt in 2025, 2.7% of world trade (IGU World LNG Report 2026 via
[Oman Observer](https://www.omanobserver.om/article/1192704/business/oman-lng-exports-reach-119-million-tonnes)).
Nameplate is 10.4 Mtpa (IGU), raised to 11.5 Mtpa by an upgrade (Oman Observer). In 2026 Oman became
India's top LNG supplier while Qatari cargoes were stuck
([NGS India](https://ngsindia.org/news/oman-beats-qatar-as-indias-top-lng-supplier-as-war-disrupts-gulf-gas-flows/)).

## Headline facts

| Fact | Value | Year | Source |
|---|---|---|---|
| Share of world LNG trade through Hormuz | about 20% | 2024 | [EIA, 24 Jun 2025](https://www.eia.gov/todayinenergy/detail.php?id=65584) |
| Qatar / UAE LNG through Hormuz | 9.3 / 0.7 bcf/d | 2024 | EIA (same) |
| Share of Hormuz LNG going to Asia | 83% | 2024 | EIA (same); China, India and Korea took 52% |
| LNG through Hormuz | over 110 bcm | 2025 | [IEA, Strait of Hormuz](https://www.iea.org/about/oil-security-and-emergency-response/strait-of-hormuz) |
| Share of world LNG trade through Hormuz | almost 20% | 2025 | [IEA factsheet, Feb 2026](https://iea.blob.core.windows.net/assets/c8248eba-8689-46d9-ae4b-b858b59c0f1c/StraitofHormuz2026-Factsheet.pdf) |
| Share of Hormuz LNG going to Asia | almost 90% (Europe just over 10%) | 2025 | IEA factsheet (same) |
| Qatar LNG exports | 81.5 Mt (18.7% of world) | 2025 | IGU 2026 via [The Peninsula](https://thepeninsulaqatar.com/article/30/07/2026/qatar-strengthens-lng-leadership-as-exports-reach-record-high-in-2025) |
| Qatar LNG exports | 77.23 Mt | 2024 | IGU 2025 via [SAFETY4SEA](https://safety4sea.com/igu-world-lng-report-lng-trade-grew-by-2-4-in-2024/) |
| UAE LNG exports | about 7 bcm | 2025 | IEA factsheet (same) |
| World LNG trade | 436.98 Mt | 2025 | IGU 2026 via [OGJ](https://www.ogj.com/general-interest/economics-markets/news/55392446/global-lng-trade-hits-record-in-2025-as-2026-tests-market-resilience) |
| World LNG trade | 411.24 Mt | 2024 | IGU 2025 via [IIR](https://iifiir.org/en/news/world-lng-report-2025-lng-trade-continues-to-grow-requiring-increased-global-decarbonisation-efforts) |
| Qatar LNG to the EU and UK | 9.2 Mt | 2025 | [Kpler](https://www.kpler.com/blog/middle-east-conflict---gas-market-implications-a-continuing-assessment) |
| Qatar capacity lost to the 2026 strikes (trains 4 and 6) | 12.8 Mtpa | 2026 | [GIIGNL Annual Report 2026](https://giignl-documents.s3.fr-par.scw.cloud/public/giignl-2026-annual-report.pdf) |

The IEA factsheet's 112 bcm figure is ambiguous in the snippets (Qatar's exports or the total through the
strait), so the JSON uses the IEA page's "over 110 bcm" for the strait.

## To verify on the primary pages

All of it, since nothing was read on the primary page. In order of weight on the map: China, India,
Taiwan, Korea and Pakistan; then the three EU estimates; then the Bangladesh single source.
