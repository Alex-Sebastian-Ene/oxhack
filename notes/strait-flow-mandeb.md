# Bab el-Mandeb flow estimator on synthetic scenarios

Generated 2026-10-25 02:27 UTC by `uv run experiments/strait_flow.py --strait mandeb`. **All ships are SYNTHETIC**: each scenario is calibrated so the true laden flow through the gate, both directions added, matches a published figure. The estimator then sees only what AIS and two radar passes would show. Units: million barrels/day.

| Scenario | Seed | Published (calibration) | True (synthetic) | Seen on AIS | Bridged gaps | Never seen (radar) | Estimate (90% range) | Truth in range |
|---|---|---|---|---|---|---|---|---|
| Pre-crisis 2023 | 10 | 8.70 | 8.56 | 8.33 | 0.14 | 0.52 | 9.04 (8.22-10.86) | yes |
| 2024 after the Houthi attacks | 9 | 4.00 | 4.30 | 4.28 | 0.00 | 0.52 | 4.81 (4.22-6.61) | yes |
| Q2 2026, Hormuz shut, Saudi crude via Yanbu | 8 | 8.10 | 8.17 | 7.06 | 0.94 | 0.52 | 8.56 (7.77-10.39) | yes |
| Sep 2026, Houthi blockade of Saudi shipping | 15 | 2.56 | 2.41 | 1.88 | 0.00 | 0.52 | 2.40 (1.90-4.18) | yes |

A 48-hour window at these flows holds on average only 5 to 23 laden tankers, so one draw can land far from the figure it is calibrated to (the mean over many seeds matches it). Each scenario shows the first seed from 7 whose true flow is within 10% of the published figure; the choice looks at the truth only, never at the estimate. In all 4 windows shown neither radar pass caught a tanker that never used AIS, so the never-seen figure there is the zero-count prior alone.

How often the 90% range covers the truth, over 40 other random seeds per scenario (1000 draws each): Pre-crisis 2023 39/40 (median estimate / truth 1.06); 2024 after the Houthi attacks 38/40 (median estimate / truth 1.12); Q2 2026, Hormuz shut, Saudi crude via Yanbu 39/40 (median estimate / truth 1.05); Sep 2026, Houthi blockade of Saudi shipping 34/40 (median estimate / truth 1.20). Every miss is an over-estimate. Most windows hold no dark tanker that a radar pass catches. The radar count is then zero, and its Jeffreys prior still adds a median of 0.52/0.52/0.53/0.52 mb/d of never-seen flow (same order). That is what lifts the range above a small truth, and why the lowest-flow scenario covers least.

## Where each scenario's numbers come from

Figures were read from search-result snippets on 25 Oct 2026 because our cloud session cannot open eia.gov or the news sites: **verify at source** before quoting.

### Pre-crisis 2023 (EIA: 8.7 mb/d)

- Flow: EIA Today in Energy, Sep 2024 (Vortexa data): 8.7 mb/d of crude and products in 2023. EIA's chokepoint table (Mar 2026 edition) has 9.3 for 2023, its Jun 2024 edition 8.6; a secondary summary of EIA data gives 8.8 for 1H 2023.
- Direction: 50% of laden barrels southbound. No published split by direction found. A Kpler explainer gives 2023 peaks of 7.7 a day northbound and 7.2 a day southbound (units unclear in the snippet), so half each way.
- Dark ships: AIS gap across the gate 3% of tankers, never on AIS 2%, spoofed positions 1%. Of the tankers with AIS on, 0% broadcast a security message instead of a destination. Same low baseline as Hormuz before the war; no published dark share for 2023 found.
- Other ships: 20 a day each way, for the picture only. About 51 transits a day in Oct 2023 (BigOceanData sample of AIS), less the tankers.

### 2024 after the Houthi attacks (EIA: 4.0 mb/d)

- Flow: EIA Today in Energy, Sep 2024 (Vortexa data): 4.0 mb/d in Jan-Aug 2024, while flows round the Cape of Good Hope rose from 6.0 to 9.2 mb/d. EIA's table: 4.1 for all of 2024.
- Direction: 50% of laden barrels southbound. No published split by direction found: half each way (assumption).
- Dark ships: AIS gap across the gate 6% of tankers, never on AIS 5%, spoofed positions 1%. Of the tankers with AIS on, 40% broadcast a security message instead of a destination. About 10% of merchant passings were dark (risk report, Feb 2024); dark-fleet ships were 13-15% of transits in Sep-Oct 2024 (Kuehne+Nagel; a different measure). Share broadcasting a security message assumed.
- Other ships: 7 a day each way, for the picture only. About 19 transits a day in Jun 2024 (BigOceanData sample of AIS), less the tankers.

### Q2 2026, Hormuz shut, Saudi crude via Yanbu (EIA: 8.1 mb/d)

- Flow: EIA STEO, Aug 2026, as reported by Connaissance des Energies (AFP) and Il Foglio: 8.1 mb/d in Q2 2026, against 5.6 in Q1 2026 and 5.4 before the war. Kpler: 7.4 mb/d in Jun-Jul 2026.
- Direction: 75% of laden barrels southbound. Saudi crude from Yanbu heads mostly south to Asia (Wood Mackenzie, Jun-Jul 2026: no direct European deliveries; cargoes for Ain Sukhna go north without crossing the strait). The 75% share is our assumption.
- Dark ships: AIS gap across the gate 6% of tankers, never on AIS 4%, spoofed positions 2%. Of the tankers with AIS on, 50% broadcast a security message instead of a destination. Kpler daily counts: 4 dark of 49 crossings on one Jul 2026 day, 3 of 26 on 7 Aug (via news reports); Saudi-laden tankers crossed with transponders off (Bloomberg via gCaptain, citing Vortexa and Kpler). Share broadcasting a security message assumed.
- Other ships: 15 a day each way, for the picture only. 42.5 vessel crossings a day on 1-19 Jul 2026, 32.1 on 20-28 Jul (shipping data quoted in Jul 2026 coverage; source article not pinned), less the tankers.

### Sep 2026, Houthi blockade of Saudi shipping (Kpler: 2.56 mb/d)

- Flow: Kpler preliminary data via The National, 29 Sep 2026: 2.56 mb/d through Bab el-Mandeb in Sep, from 5.45 in Aug; Saudi flows through the strait 0.45 mb/d in Aug.
- Direction: 60% of laden barrels southbound. Saudi flows south collapsed (0.45 mb/d in Aug); 60% south is our assumption.
- Dark ships: AIS gap across the gate 20% of tankers, never on AIS 20%, spoofed positions 3%. Of the tankers with AIS on, 70% broadcast a security message instead of a destination. After the 20 Jul 2026 blockade, one report says most ships trying to cross switch transponders off; a 2026 headline says four in five ships talk their way past. Neither gives a measured share, so 40% dark and 70% messaging are assumptions.
- Other ships: 10 a day each way, for the picture only. IMF PortWatch: 24.7 transits a day in the week to 20 Sep 2026 (via Statistics of the World), less the tankers.

## Assumptions shared by all scenarios

- Tankers laden: 85% southbound, 75% northbound (the rest in ballast). The estimator does not know this: it reads laden from draught for AIS ships and draws a laden share of 0.6-0.98 for dark ones.
- Tanker sizes: before 2026 VLCC 10%, Suezmax 30%, Aframax/LR2 25%, MR 35% (assumption: a laden VLCC is too deep for the Suez Canal); 2026 scenarios use the Hormuz mix because Yanbu cargoes to Asia went on VLCCs.
- Crude share 45%-60%: assumption, no published split for the strait found.
- Radar corridor: lon 43.05-44.5, two passes in the 48 hours, as for Hormuz. Real Sentinel-1 revisit over the strait is unconfirmed.
- Lanes and gate: `experiments/strait_geo.py --strait mandeb`, approximate, not for navigation.

Method: `docs/strait-live-data.md` (sections 3 and 7). Hormuz results: `notes/strait-flow.md`.
