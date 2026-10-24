# Live data for the Strait of Hormuz: what we built and why

Written 24 Oct 2026. Research came mostly from search-result snippets, because our cloud sessions
cannot reach most of these sites; anything marked *unconfirmed* needs checking at its source before
it goes on a slide.

**Try it:** open `ui/strait/index.html` in a browser (no server needed) or the published page.
**Code:** `experiments/strait_geo.py` (map), `experiments/strait_flow.py` (estimator, ghost score,
simulator), `experiments/strait_sources.py` (real-data collectors), `experiments/strait_bundle.py`
(one-file build). Tests: `tests/test_strait_flow.py`.

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
