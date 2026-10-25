# Gas pipelines in and around the Gulf (research desk, 25 Oct 2026)

Data for the map's gas lines: `experiments/gas_routes.py` writes `ui/app/data/gas.json`.
LNG flows are in `lng-flows.md`.

**How collected:** web search on 25 Oct 2026; primary sites were blocked, so **every figure is from
search-result snippets** (`"verify": true`). URLs accessed 25 Oct 2026. Paths are a handful of
waypoints along the real route and are approximate (`"approx": true`). `capacity_bcm_y` in the JSON
converts each capacity to bcm a year (1 bcf/d = 10.34 bcm/y, 1 mcm/d = 0.365 bcm/y) so widths share
one scale.

| Pipeline | Capacity | Other numbers | Status | Bypasses Hormuz |
|---|---|---|---|---|
| Dolphin, Ras Laffan to Taweelah (QAT to ARE) | 3.2 bcf/d design (33 bcm/y) | 364 km, 48 in, subsea; delivers about 2 bcf/d | operating since 2007 | yes, but wholly inside the Gulf |
| Dolphin, Taweelah to Fujairah (ARE) | 1.6 bcf/d (16.5 bcm/y) | 244 km, 48 in, crosses the Hajar mountains | operating (about 2010) | yes: Qatari gas to the Gulf of Oman coast |
| Dolphin to Oman, Al Ain to Sohar (ARE to OMN) | 200 MMscf/d contracted (2.1 bcm/y) | 25-year contract from 2005 | operating since Nov 2008 | yes |
| Iran to Turkey, Tabriz to Ankara | 14 bcm/y | 2,577 km; contract 9.6 bcm/y; 7.81 bcm in 2025 (13.5% of Turkey's imports) | operating since 2001; contract reported expired 29 Jul 2026 | yes, overland |
| Iran to Iraq, Naft Shahr to Baghdad | 25 mcm/d for three Baghdad plants (9.1 bcm/y) | Iraq's contract up to 50 mcm/d (renewed 2024); at most 15 mcm/d in Apr 2026 | operating, cut in 2026 | yes, overland |
| Iran to Iraq, Shalamcheh to Basra | 25 mcm/d (9.1 bcm/y) | 141 km, 48 in, branch of IGAT-6 | built; regular flows not confirmed | yes, overland |
| Iran to Pakistan (IP) | 750 MMcf/d design (7.8 bcm/y) | Pakistani section about 781 km | Iranian side built, Pakistani side not; no gas has flowed | would be |

## Sources

- **Dolphin main line:** [Offshore Technology](https://www.offshore-technology.com/projects/dolphin-gas/)
  (364 km, 48 in, 3.2 bcf/d design); [Dolphin Energy operations](https://www.dolphinenergy.com/operations);
  [Gulf News](https://gulfnews.com/business/energy/dolphin-energy-is-to-raise-gas-flow-to-uae-1.623037)
  (2 bcf/d delivered). Energy Intelligence reported a 200 MMcf/d cut for maintenance in Jan 2026.
- **Taweelah to Fujairah:** [Gulf News](https://gulfnews.com/business/energy/dolphin-energy-completes-taweelah---fujairah-pipeline-1.720870)
  and [MEED](https://www.meed.com/dolphin-energy-completes-cross-uae-gas-pipeline/) (1.6 bcf/d, 244 km).
  Global Energy Monitor lists "1.6 bcm/y", which looks like a unit slip. Completion year is approximate.
- **Dolphin to Oman:** [Oil & Gas Journal](https://www.ogj.com/pipelines-transportation/article/17267973/dolphin-energy-begins-supplying-gas-to-oman)
  (200 MMscf/d via Al Ain; Oman's own line runs from Al Buraimi to Sohar).
- **Tabriz to Ankara:** [Global Energy Monitor](https://gem.wiki/Tabriz-Ankara_Pipeline) (14 bcm/y, 2,577 km,
  operating since July 2001); [MEES, 24 Apr 2026](https://www.mees.com/2026/4/24/news-in-brief/turkey-open-to-iran-gas-contract-extension/8161dba0-3fcb-11f1-a220-af3d2a70a45d)
  (7.81 bcm in 2025); [The New Arab / Reuters](https://www.newarab.com/news/turkey-says-iran-gas-pipeline-contract-nearing-expiry)
  (9.6 bcm/y contract, last met in 2022). The lapse on 29 Jul 2026 and continued flows on temporary terms
  come from one outlet ([Al Maktoum Office](https://almaktoumoffice.com/news/turkey-iran-gas-squeeze-2026)).
  Route: Tabriz, Bazargan, Dogubayazit, Erzurum, Erzincan, Sivas, Kayseri, Ankara (Turkish energy ministry).
- **Naft Shahr to Baghdad:** [Argus](https://www.argusmedia.com/en/news-and-insights/latest-market-news/927476-iraq-insecurity-delays-iran-gas-project)
  (up to 25 mcm/d for the Mansuriya, Quds and Baghdad plants);
  [S&P Global, Apr 2026](https://www.spglobal.com/energy/en/news-research/latest-news/shipping/042726-iraq-faces-critical-gas-shortage-as-middle-east-war-cuts-vital-imports)
  (contract up to 50 mcm/d; imports "do not exceed 15 mcm/d"). Other reports put early-April flows at
  about 5 mcm/d. Start year (about 2017) is approximate.
- **Shalamcheh to Basra:** [Shana](https://en.shana.ir/news/280695/Shana) (terminal maximum 25 mcm/d; flows
  waited on Basra's side); [Natural Gas World](https://www.naturalgasworld.com/iran-operates-second-line-to-basra-56262)
  (141 km, 48 in, from IGAT-6). Sources found date from 2015 to 2018.
- **Iran to Pakistan:** [World Pipelines, Feb 2024](https://www.worldpipelines.com/business-news/27022024/first-phase-of-iran-pakistan-gas-pipeline-approved/)
  (750 MMcf/d to about 1 bcf/d design; Pakistan approved an 80 km first phase to Gwadar). Iran says its
  side is built (about 900 km Asaluyeh to Iranshahr, 56 in). Status in 2026 not confirmed.

## Why these

- A Hormuz closure strands Qatari and UAE LNG but not Dolphin's pipeline gas, which reaches the UAE and
  Oman inside the Gulf and then Fujairah on the far side of the strait.
- Iran's exports to Turkey and Iraq go overland, so the strait does not touch them; the 2026 strikes on
  Iranian gas plants did, and Iraq's power plants lost much of their fuel.
- IP is the Hormuz-free option Pakistan never finished, while it took 99% of its LNG from the Gulf.

Left out: the Arab Gas Pipeline (Egypt to Jordan, Syria and Lebanon) carries Egyptian and Israeli gas,
not Gulf gas, so a closure does not change it. Saudi Arabia's Master Gas System is domestic only.
