# Live data for the Strait of Hormuz: what we built and why

Written 24 Oct 2026. Research came mostly from search-result snippets, because our cloud sessions
cannot reach most of these sites; anything marked *unconfirmed* needs checking at its source before
it goes on a slide.

**Try it:** open `ui/strait/index.html` in a browser (no server needed) or the published page.
Add `?strait=mandeb` for Bab el-Mandeb (section 7).
**Code:** `experiments/strait_geo.py` (map), `experiments/strait_flow.py` (estimator, ghost score,
simulator), `experiments/strait_sources.py` (real-data collectors), `experiments/strait_bundle.py`
(one-file build). The first two take `--strait mandeb`. Tests: `tests/test_strait_flow.py`,
`tests/test_strait_mandeb.py`.

## 1. Can it be live? No, not for free

| Source | Delay from ship being there to us having the data | Free? |
|---|---|---|
| Terrestrial AIS | under 1 min, where receivers exist | **No free receivers in Hormuz** ([test of AISStream](https://github.com/yasumorishima/hormuz-ship-tracker)) |
| Satellite AIS (Kpler/Spire) | median 11–48 min ([Spire docs](https://documentation.spire.com/?p=186)) | Paid, enterprise only |
| GFW AIS presence | 72–96 h | Free, non-commercial |
| GFW events (gaps, loitering, port visits) | ~72 h | Free, non-commercial |
| GFW radar (SAR) detections | ~5 days | Free, non-commercial |
| Raw Sentinel-1 radar scene | ~1–24 h after the pass (3 h typical), passes days apart ([ESA](https://sentinel.esa.int/web/sentinel/sentinel-1-data-products)) | Free |
| IMF PortWatch daily transits | 3–10 days | Free |

**Decision:** the app never says "live". The map plays a 48-hour window and every view says how
old its data is. Today it plays a **simulation calibrated to published figures**; the collectors
in `strait_sources.py` fill the same structure with real observations once the network allows.

**Why simulate rather than show nothing:** the judges need to see ships flowing, and the estimator
needs a known truth to prove it works. In the simulation we know the true flow, so the page shows
our estimate next to it (the ✓ figure). Everything simulated is badged SIMULATED, and every ship
identity is fictional.

**Optimisations we chose:**
- Query only a bounding box around the strait (54.6–57.9°E, 24.9–27.5°N) and only tankers.
- Fetch incrementally and cache raw downloads under `data/raw/strait/` with a timestamp, so
  every number can say when it was collected.
- Between observations, move ships along their lane at their last speed (dead reckoning) instead
  of waiting for the next report. This is how the map stays smooth with days-old data.
- Use each radar snapshot twice: to find dark ships, and to turn a count into a rate (section 3).
- Draw on a plain canvas with the coastline bundled (Natural Earth, public domain): no map tiles,
  no CDN, so it works on venue Wi-Fi or offline.

**What would make it live:** satellite AIS from Kpler/Spire (11–48 min) plus tasked radar from
Umbra, ICEYE or Capella. Umbra's prices run from about $675 per 5×5 km scene at 0.5–1 m
([SkyFi, Aug 2025](https://skyfi.com/files/SkyFi_Pricing_August_2025.pdf)). Out of scope for a
weekend, but the natural "next step" slide.

## 2. Identifying ships: registries and satellite images

**What a satellite can and cannot tell us.** Sentinel-1 radar (about 20 m pixels) gives position,
rough length (about ±14% for classical methods,
[JRC](https://publications.jrc.ec.europa.eu/repository/handle/JRC101029)) and sometimes heading.
That separates a 330 m VLCC from a 180 m MR tanker, but not Suezmax from Aframax reliably, and it
can **never** read a name or flag. Hull lettering needs very high resolution (around 30 cm,
our estimate) and a lucky angle. Sentinel-2 optical (10 m) adds colour and wake but needs clear
skies.

**Decision:** identity comes from **matching** a radar detection to an AIS track. We interpolate
each AIS track to the image time and match within 30 min / 5 km. An unmatched tanker-sized
detection is a dark ship. Its nationality is "unknown", and we say so rather than guess. For
running our own detector on raw scenes, Ai2's Apache-licensed
[`vessel-detection-sentinels`](https://blog.allenai.org/protecting-marine-life-with-ai-192529f8aa15)
is the weekend option. GFW's `public-global-sar-presence` dataset already flags matched and
unmatched detections, which saves us running a model at all.

**Registry lookups, in order of use:**
1. **MMSI → flag** from the first three digits (Maritime Identification Digits, ITU Radio
   Regulations Appendix 43). Instant and offline. It shows the flag a ship *claims*, not one a
   registry confirms.
2. **IMO check digit** (weights 7..2 on the first six digits). Catches made-up numbers; a failure
   is a warning, not proof.
3. **GFW Vessels API** (`public-global-vessel-identity`). Gives registry info, owners and
   authorisations from 40+ registries. Coverage of tankers is unconfirmed: GFW has no "tanker"
   type, so they come back as cargo or other.
4. **Sanctions lists by IMO:** [OpenSanctions maritime](https://www.opensanctions.org/datasets/maritime/)
   (about 19k vessels, CC BY-NC) and OFAC SDN (public domain).
5. **Manual only, for showcase ships:** Equasis (flag, owner and insurance history), IMO GISIS and
   ITU MARS. None has an API, and scraping them is likely against their terms.

## 3. Estimating the oil actually moving

Three signals, added up, each with a range:

1. **Seen:** laden tankers whose AIS track crosses a gate line across the narrows (56.42°E),
   outbound only, after dropping positions that imply more than 40 knots. Cargo comes from the
   size class and a 0.88–1.0 load factor, and laden-or-empty from draught against design draught.
2. **Bridged gaps:** a ship that switches AIS off on one side of the gate and reappears on the
   other certainly crossed. This was a real bug in our first version: the straight line between
   the two positions cuts the corner of the curved lane and misses the gate, so we test for a jump
   across the gate's meridian instead.
3. **Never on AIS (radar + Little's law):** count tanker-sized radar detections in a corridor about
   one Sentinel-1 swath wide (about 250 km) that match no AIS track and no bridged ship (L). Divide
   by the time a tanker takes to cross the corridor (W). L / W is the hourly crossing rate of
   ships we never see on AIS. One pass sees only a handful of ships, so the count is treated as
   Poisson (Jeffreys prior) and the range widens honestly.

The range comes from 4,000 random draws over the uncertain inputs: load factor, radar recall
0.8–0.95, false positives 0–8%, laden share of dark ships 0.6–0.98, and speed 10.5–14.5 kn.

**Does it work?** On the synthetic scenarios (`notes/strait-flow.md`) the 90% range covered the
true value in 60 of 60 random runs (20 per scenario), and the tests check this every time. AIS
alone recovered about 93% of the true flow in the pre-war scenario but only about 47% in the 2026
ones.

**Extrapolating to the world:**

| Figure | Value | Source |
|---|---|---|
| World oil demand 2026 | 103.3 mb/d | [IEA OMR, Aug 2026 (via Argus)](https://www.argusmedia.com/en/news-and-insights/latest-market-news/2864083-iea-sees-greater-oil-demand-fall-in-2026) |
| Share of oil moved by sea | ~76% (77.5 of 101.9 mb/d, 2023) | [EIA chokepoints](https://www.eia.gov/international/content/analysis/special_topics/World_Oil_Transit_Chokepoints/wotc.pdf) |
| Pre-war Hormuz flow | 20 mb/d (2024), 20.9 mb/d (1H25) | [EIA](https://www.eia.gov/todayinenergy/detail.php?id=65504) |
| Hormuz Q1 2026 | 14.6 mb/d | [EIA quarterly dataset, via World Oil](https://worldoil.com/news/2026/5/12/eia-launches-new-oil-lng-chokepoint-datasets-amid-hormuz-crisis/) |
| Crude vs products through Hormuz | 72–75% crude | EIA and [IEA](https://www.iea.org/about/strait-of-hormuz), 2025 |
| Other chokepoints, 1H25 | Malacca 23.2, Suez+SUMED 4.9, Danish straits 4.9, Bab el-Mandeb 4.2, Turkish straits 3.7 mb/d | EIA |

The page shows our estimate as a share of world demand and of seaborne oil, and the shortfall
against the pre-war 20 mb/d. It also lines our estimate up against the published 2026 figures
(Vortexa ~3.5, Argus ~3.7, Windward ~8.9 and US officials ~10 mb/d, Aug–Sep 2026), because the
disagreement between them is the story. For late October, straits.live reports PortWatch counting
4 transits on 18 Oct against about 85 normally, while Kpler puts Middle East outflows at 13.1 mb/d.
That gap between AIS counts and what actually flows is exactly what we measure. (Aggregator figures;
verify at source.)

## 4. Ghost-ship score

A score from 0 to 1 that starts from a low prior and adds evidence. Each rule matches an indicator
analysts publish. The weights are our judgement and should be tuned on reviewed examples.

| Indicator | Weight (log-odds) | Why it counts |
|---|---|---|
| Radar sees it, AIS never on | 2.5 | The definition of dark |
| AIS off inside the strait | 1.5 | First indicator in the [2020 US maritime advisory](https://crowell.com/en/insights/client-alerts/new-u-s-sanctions-advisory-for-the-maritime-industry) |
| IMO on a sanctions list | 2.0 | OFAC / OpenSanctions |
| Claims a registry known for false flags | 1.5 | Guinea, Netherlands Antilles (dissolved 2010), Guyana and Aruba were the most used at end-2025 ([Windward](https://windward.ai/knowledge-base/false-flags-fraudulent-registries-and-the-dark-fleet/)) |
| IMO fails its check digit | 1.5 | Fabricated and "zombie" identities ([Lloyd's List](https://www.lloydslist.com/LL1155512/From-zombie-tankers-to-fake-IMO-numbers-the-identity-frauds-now-playing-out-at-sea)) |
| MMSI flag differs from registry flag | 1.0 | Flag hopping and false flags |
| Met another tanker at sea | 1.0 | Ship-to-ship transfers. Hotspots: Eastern OPL off Johor, Malaysia (42 Iranian transfers since 28 Feb 2026, [AP via WTOP](https://wtop.com/world/2026/05/malaysia-says-it-can-do-little-to-stop-iranian-linked-oil-transfers-near-its-water/)); Fujairah and Sohar are busy but mostly legitimate |
| 2+ flag changes in 12 months | 0.8 | Ships cycling through up to 5 flags in 6 months ([Windward](https://windward.ai/blog/gambia-deletes-shadow-fleet-tankers-in-second-flag-governance-crackdown/)) |
| Owner unknown or single-ship shell | 0.8 | Lloyd's List dark-fleet definition |
| 15 or more years old | 0.6 | Same definition: 15+ years **and** opaque ownership ([Lloyd's List](https://www.lloydslist.com/LL1144787/Shifty-shades-of-grey-The-different-risk-profiles-of-the-dark-fleet-explained)) |
| Position unreliable (impossible jumps) | 0.6 | Kept low on purpose. Gulf jamming in 2026 hit 1,100+ ships in a day ([Windward](https://windward.ai/blog/gps-jamming-disrupts-1100-ships-in-the-middle-east-gulf/)), honest ships included, so this means "position unreliable" more than "hiding" |
| Destination blank or "FOR ORDERS" | 0.3 | Weak signal; also common in legitimate trade |

Not yet scored, but worth adding with real data: lack of International Group P&I insurance (from
Equasis), loitering and port visits (GFW events), draught changes without a port call, and
destination fields edited to announce nationality ("China owner"), as seen in March 2026
([CLS](https://maritime-intelligence.groupcls.com/gnss-spoofing-strait-of-hormuz/)). Context for the
pitch: estimates of the shadow fleet run from about 670 (Lloyd's List) to over 1,300 tankers
(Chatham House, Sep 2026), about 1 in 5 of the world's tankers.

## 5. The map UI

- **Zoom and pan:** + / − / fit buttons, scroll wheel, drag, pinch on phones, arrow keys and + / −
  on the keyboard.
- **Symbols over text:**
  - Blue triangle: tanker on AIS (filled when laden).
  - Dashed amber ring: dark tanker.
  - Amber dot: likely ghost.
  - ✕: fake AIS position.
  - White square: radar detection.
  - Eye and eye-with-slash: seen and dark counts.
  - Each warning in the ship pop-up has its own icon: flag, ID card, hourglass, ban sign and so on.
- **Text behind ⓘ buttons:** the map key, how the estimate works, the global figures and the
  simulation notice. Names appear in tooltips.
- **Two views:** "what AIS shows" hides dark ships, the way trackers see the strait; "everything"
  shows them. Switching between the two makes the point in one click.

## 6. Next steps

1. On a laptop with a GFW token: `uv run experiments/strait_sources.py check`, then `fetch`.
   Confirm the UNVERIFIED endpoints (PortWatch layer, OpenSanctions path, GFW 4Wings parameters).
2. Count real Sentinel-1 passes over Hormuz from the Copernicus catalogue; the revisit there is
   unconfirmed (likely 2–6 days).
3. Feed real rows through `observations_to_sim` and publish a "cached, collected <date>" scenario
   alongside the simulated ones.
4. Tune the ghost weights on a dozen hand-checked ships (Equasis, GISIS, MARS).

## 7. Bab el-Mandeb

Added 25 Oct 2026. The same model, for the strait between Yemen and Djibouti:

    uv run experiments/strait_geo.py --strait mandeb    # ui/strait/data/mandeb-geo.json
    uv run experiments/strait_flow.py --strait mandeb   # ui/strait/data/mandeb-scenarios.js, notes/strait-flow-mandeb.md

`mandeb-scenarios.js` sets `window.STRAITS.mandeb`, with the same shape as `window.STRAIT` plus one
key, `geo.lat0` (12.6), the latitude for turning degrees into km. A reader that hard-codes Hormuz's
26.4 still works but draws the map about 8% too narrow. Hormuz output is unchanged; a test checks it.

**Map.** View 42.5–44.5°E, 11.8–13.6°N. Two lanes run through the main channel west of Perim
(Mayyun), where the traffic separation scheme is about 40 km long
([CNES](https://cnes.fr/sites/default/files/drupal/202107/default/2021-035_6_expo_frontieres_babelmanded_a0-bd.pdf)).
Southbound ships (out of the Red Sea, `outbound`) keep to the western lane and northbound ships
(`inbound`) to the eastern one. North of the strait both lanes pass east of the Hanish islands, as
the IMO scheme off Jabal Zuqar does (COLREG.2/Circ.52, 2003). The gate runs along 43.41°E from the
Djibouti shore to Perim and closes the southern mouth of the main channel. It is a meridian, not the
narrowest line, because the estimator and the map find crossings by the gate's meridian;
`strait_geo.py` refuses a gate that is not one, and any lane or gate that touches land. Lanes are
approximate, never for navigation.

**What changes from Hormuz.**
- Laden tankers cross both ways, so both lanes are counted. Hormuz counts only the outbound lane.
- The radar corridor is the whole lane. The lanes span about 160 km east to west, inside one
  250 km Sentinel-1 swath. Dark detections from both lanes are pooled into one Little's-law count.
- A 48-hour window holds only about 5 to 23 laden tankers, so one draw can land far from its
  published figure. The page shows the first seed whose true flow is within 10% of it. The choice
  looks at the truth, never at the estimate.
- Ghost behaviour uses the same mechanisms: AIS gaps across the gate (bridged), tankers never on
  AIS (radar only) and spoofed jumps. Ships with AIS on may broadcast a security message such as
  "ALL CHINESE CREW" instead of a destination, as reported in July 2026
  ([Aaj TV](https://english.aaj.tv/news/330464718),
  [Al-Monitor](https://al-monitor.com/originals/2026/07/tankers-keep-sailing-red-sea-despite-houthi-threats-saudi-oil-lifeline-faces)).

**Scenarios** (all ships SYNTHETIC; results in `notes/strait-flow-mandeb.md`):

| Scenario | Calibrated to | Dark tankers (gap + never on AIS) | Basis for the dark share |
|---|---|---|---|
| Pre-crisis 2023 | 8.7 mb/d, EIA (Vortexa data), 2023 average | 3% + 2% | Hormuz pre-war baseline; nothing published |
| 2024 after the Houthi attacks | 4.0 mb/d, EIA (Vortexa data), Jan–Aug 2024 | 6% + 5% | about 10% of passings dark, Feb 2024 ([risk report via HKSOA](https://hksoa.org/wp-content/uploads/2024/02/MC2416-Annex-A-Monthly-Intelligence-Report-February-2024.pdf)) |
| Q2 2026, Hormuz shut, Saudi crude via Yanbu | 8.1 mb/d, EIA STEO Aug 2026 | 6% + 4% | Kpler daily counts: 3 of 26 crossings dark on 7 Aug 2026 ([via Libnanews](https://live.libnanews.com/event/ev-1786145397634-a146)), 4 of 49 on one July day (news reports, article not pinned) |
| Sep 2026, Houthi blockade of Saudi shipping | 2.56 mb/d, Kpler preliminary, Sep 2026 | 20% + 20% | assumption; one report says most ships cross with transponders off |

On 40 fresh seeds per scenario, the 90% range covered the truth 39, 38, 39 and 34 times. Every
miss was an over-estimate. When radar catches no dark tanker, the count is zero and its Jeffreys
prior still adds about 0.5 mb/d, which matters most at 2.56 mb/d.

**The knock-on from Hormuz.** With Hormuz shut from late February 2026, Saudi Arabia moved crude
through its East-West pipeline to Yanbu on the Red Sea. Most of it sailed south through Bab
el-Mandeb to Asia: no direct European deliveries were recorded in June–July
([Wood Mackenzie](https://www.woodmac.com/press-releases/saudi-arabias-red-sea-crude-bypass-peaks-in-march-and-declines-41-by-june/)).
Flow through the strait rose from about 5.4 mb/d before the war to 8.1 in Q2 2026 (EIA). The
Houthis declared a blockade of Saudi shipping on 20 July 2026. By September the strait carried
2.56 mb/d, and Saudi barrels had moved back to Hormuz (2.58 mb/d in September, Kpler via The National).

**Published figures** (read from search-result snippets on 25 Oct 2026; eia.gov and the news sites
could not be opened from our cloud session, so **verify at source**):

| Figure | Value (mb/d) | Source |
|---|---|---|
| 2023 average | 8.7 | [EIA Today in Energy, Sep 2024](https://www.eia.gov/todayinenergy/detail.php?id=63446) (Vortexa data) |
| 2023 in EIA's chokepoint table | 9.3 (Mar 2026 edition), 8.6 (Jun 2024 edition) | [EIA World Oil Transit Chokepoints](https://www.eia.gov/international/content/analysis/special_topics/World_Oil_Transit_Chokepoints) |
| 1H 2023 | 8.8 | secondary summary of EIA data; the [Dec 2023 EIA article](https://www.eia.gov/todayinenergy/detail.php?id=61025) has it only in a chart |
| Jan–Aug 2024 | 4.0 (Cape of Good Hope 6.0 → 9.2) | EIA Today in Energy, Sep 2024 |
| 2024; 1H 2025 | 4.1; 4.2 | EIA chokepoint table, Mar 2026 edition |
| Before the war; Q1 2026; Q2 2026 | 5.4; 5.6; 8.1 | EIA STEO Aug 2026, via [Il Foglio](https://www.ilfoglio.it/en/economy/2026/08/13/news/the-attack-on-bab-el-mandeb-and-the-crude-oil-shortage-paltrinieri-speaks-out--404739) and [Connaissance des Energies (AFP)](https://www.connaissancedesenergies.org/afp/le-detroit-de-bab-el-mandeb-lautre-passage-maritime-strategique-menace-260910) |
| Jun–Jul 2026 | 7.4 | Kpler, via [Energy Connects](https://www.energyconnects.com/opinion/features/2026/july/bab-el-mandeb-tanker-attacks-challenge-alternative-oil-routes/) |
| Aug 2026; Sep 2026 | 5.45; 2.56 | Kpler preliminary, via [The National, 29 Sep 2026](https://www.thenationalnews.com/business/energy/2026/09/29/oil-flows-through-strait-of-hormuz-rise-on-saudi-pivot-as-red-sea-traffic-plunges/) |
| Yanbu crude exports | 3.8 average Mar–Jul 2026, 1.5 in Aug | Kpler, via Connaissance des Energies (AFP) |

**Assumptions with no published source:** the split by direction (50% south in 2023 and 2024, 75%
in Q2 2026, 60% in Sep 2026), the laden share each way (85% south, 75% north), the tanker size mix
before 2026 (fewer VLCCs, since a laden VLCC is too deep for the Suez Canal), the crude share
(45–60%) and the dark shares for Sep 2026. Real collectors for this strait are not written yet:
`strait_sources.py` covers Hormuz only. PortWatch's id for Bab el-Mandeb is `chokepoint4`, already
used by `experiments/flow_events.py`.
