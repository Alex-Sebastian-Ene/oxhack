# Ideas: features, demo moments, data

Brainstorm from 24 Oct 2026. Nothing here is decided; move what we pick into `docs/design.md`.
The UI sketches for these live on Ed's design canvas (ask Ed for the link).

## What we must ship (core)

1. **Near-live strait view.** AIS tankers on a map of Hormuz (free AIS there lags by days; see
   Data), with a gate line across the strait that
   counts each crossing once, by direction and laden or empty.
2. **Flow estimate.** Barrels per day, split into seen and hidden, with a range and the EIA
   baseline next to it.
3. **What-if chain.** A flow slider that moves oil price → pump prices → CPI → Fed rate →
   mortgages and bills, each step showing today's value, the modelled value and a source.
4. **Provenance everywhere.** Live / cached / synthetic / modelled badge on every number.

## Features that would impress (pick two or three)

Ordered roughly by impact for effort. "Dynamic" means something visibly changes during the demo.

| # | Feature | What the judge sees | Why it lands | Effort |
|---|---|---|---|---|
| 1 | **Ghost hunter** | A radar image of a ship that has no AIS signal, matched and added to hidden flow live | The core claim made visible: we can see ships that hide | M–L |
| 2 | **Judge mode** | QR code on the slide; judges open the phone view and drag the slider; the big screen shows the room's average scenario | They play with it instead of watching it | M |
| 3 | **Number receipts** | Click any number: inputs → steps → output, plus the command to rerun it | Trust, and it answers "where did that come from?" before they ask | S–M |
| 4 | **Replay + backtest** | Press play on a past shock (2019 tanker attacks, Abqaiq, Red Sea); ships, prices and rates move day by day; model vs actual table | Proves the chain is not made up | M |
| 5 | **Draught scale** | A tanker sits deeper when full: before/after draught turns into barrels | Simple, clever physics; easy to explain | S |
| 6 | **Spoofing detector** | Tracks that jump onto land, move impossibly fast or circle; a heat map of suspect areas | Shows the data is adversarial, and that we handle it | M |
| 7 | **Model vs market** | Our Fed probabilities next to prediction-market or futures pricing; our Brent move next to the futures curve | A live, falsifiable claim | S–M |
| 8 | **Personal cost card** | "This shock costs you +$X a month", shareable, with US/UK switch | Turns oil into something everyone feels | S |
| 9 | **Who is exposed** | Destination split of Hormuz oil, reserve cover per country, and a "days until reserves run out" countdown in a closure | Global stakes, and "barrels are local, prices are global" | S–M |
| 10 | **Bypass maths** | In a closure, pipelines around the strait fill to capacity; the net loss shrinks on screen | Shows we know the system, not just the headline | S |
| 11 | **Ask the analyst** | Chat that answers from our data only and links receipts ("why did hidden flow jump?") | Natural AI use, grounded and cited | M |
| 12 | **Live pulse** | Ticker of crossings, hourly bars filling, countdown to the next satellite pass; optional sound per crossing | The strait feels alive during the pitch | S |
| 13 | **Headlines vs hulls** | News events (GDELT) on the timeline against actual tanker counts: did ships really stop when headlines said so? | A sharp insight, good for the pitch | M |
| 14 | **Shadow-fleet network** | Graph of tankers, owners, managers, flags and ship-to-ship meetings; clusters light up | Investigative feel; journalists would use it | L |
| 15 | **Ship-to-ship transfers** | Two tankers loitering side by side, both draughts change | Catches oil changing hands at sea | M |
| 16 | **Uncertainty fan** | Ranges widen at each step of the chain, as a fan chart | Honest modelling; judges with stats backgrounds notice | S–M |
| 17 | **Gas too** | Qatar's LNG also passes Hormuz: link to UK energy bills (Ofgem cap) | A UK angle for an Oxford audience | M |
| 18 | **Alerts + morning brief** | Rule builder ("tell me when hidden flow > X") and a written or spoken daily brief | Product feel; shows how it would be used daily | S |
| 19 | **Us vs the analysts** | Our flow estimate on one chart with Vortexa, Argus, Kpler, Windward and the US government figure, each dated | The real numbers disagree by 3x in 2026; we show why, with receipts | S–M |

**Suggested pick:** core + Ghost hunter (1) + Judge mode (2) + Receipts (3) + Us vs the
analysts (19), which is cheap and ties us to the 2026 news. If Ghost hunter
cannot be made real in time, swap it for Replay + backtest (4) and show the dark-ship detection
on one recorded example, labelled as cached.

## Demo moments (three minutes)

1. Open on the pulse: the latest crossings and the flow number, with how old the data is.
2. Zoom into one ghost: radar sees it, AIS doesn't; the hidden number goes up.
3. QR code: judges drag the strait shut on their phones; the big screen ripples through Brent,
   inflation, the Fed and a household's monthly bill.
4. Click a number on screen: the receipt shows exactly where it came from.
5. Close on the backtest: "on the 2019 tanker attacks, we were within X% of what happened".

## Sketches on the canvas

A command view · B what-if ripple · C ghost-ship file · D phone "what it means for you" ·
E replay + backtest · F live pulse · G number receipt · H who is exposed · I analyst chat, alerts,
brief · J judge mode · K spoofing + ship-to-ship · L us vs the analysts · M radar snapshot to flow
rate · N shadow-fleet network · O headlines vs hulls · P satellite swipe.
B, D, F, G, H, J, L, M, O and P are clickable or animated.

## Wilder ideas (parking lot)

- **Your fill-up's receipt:** of the petrol you just bought, roughly how much came through
  Hormuz, and what the strait added to the price.
- **Not just fuel:** the Gulf also ships fertiliser (urea) and petrochemicals through Hormuz
  (verify shares): a second chain to food prices and plastics.
- **Jet fuel → flights:** airline fuel costs to ticket prices; a hook for students.
- **Fear gauges:** war-risk insurance premiums and tanker freight rates as a "how scared is the
  market" dial next to the flow.
- **Prediction game:** judges guess next week's flow; we score them against our estimate when
  the data lands. A leaderboard keeps people coming back.
- **Agent investigator:** each new dark-ship suspect gets an automatic file (evidence, links,
  confidence) for a human to confirm, which also trains the detector.
- **Sound of the strait:** each crossing plays a note, hidden ones a lower note; silence when
  the strait is shut. Memorable for the opening ten seconds.
- **Bot alerts:** Telegram or Discord messages when hidden flow jumps.

## How we could estimate hidden flow

Stack several independent signals, then combine them with honest ranges. Each one alone is weak;
agreement between them is the story.

1. **Seen crossings.** A gate line across the strait; count AIS tracks that cross it, by
   direction. Drop tracks that fail the spoofing checks (impossible speed, on land, circles,
   duplicate MMSI).
2. **Cargo per ship.** Deadweight × load factor. Laden or empty from reported draught vs design
   draught. AIS draught is typed in by the crew and often stale, so treat it as a hint and
   check it against direction (outbound from Gulf terminals is usually laden).
3. **Gap bridging.** A ship goes silent on one side of the strait and reappears on the other
   within a plausible transit time: count it as a dark crossing, high confidence.
4. **Radar snapshot + Little's law.** Count tanker-sized radar detections with no AIS match in a
   corridor through the strait at one satellite pass (L). Divide by the typical time to cross that
   corridor (W) to get dark crossings per hour (λ = L / W). Turns a once-every-few-days snapshot
   into a flow rate. Clever, simple, explainable on one slide.
5. **Mass balance (stretch).** Known exports from terminals inside the Gulf, minus the bypass
   pipelines, minus what AIS sees = what must be crossing dark. Gas flaring at the fields
   (VIIRS Nightfire) as a rough check on production.
6. **Combine.** Monte Carlo over the uncertain inputs (load factor, dark weights, corridor
   time) gives a total with a range, plus how much each signal contributed.

**Validation:** on a pre-crisis period when AIS was good, hide the AIS for some ships and check
that the radar + Little's-law estimate recovers them. Compare our seen count with PortWatch, and
our total with the published 2026 estimates (see "us vs the analysts").

## Options for the economic chain

Start simple and cite every link; only add sophistication where it changes the answer.

| Link | Simple version (weekend) | Better version (if time) |
|---|---|---|
| Flow → Brent | Net supply loss × a price elasticity from the literature (e.g. Kilian 2009; Caldara, Cavallo & Iacoviello 2019: verify values) | Fit on our backtest events; subtract offsets (bypass pipelines, spare capacity, strategic reserve releases) |
| Brent → pump price | Lagged regression on EIA weekly retail vs Brent | Asymmetric pass-through ("rockets and feathers": prices rise fast, fall slowly) |
| Energy → CPI | CPI energy weight × energy price change | Second-round effects through transport and food |
| CPI → Fed | Show market pricing (Kalshi) next to a simple policy rule | Explain "look through supply shocks": inflation up but growth down |
| Fed → mortgages | 30-year rate ≈ 10-year Treasury + spread | Monthly payment for a typical loan |
| UK | Ofgem cap (quarterly lag) and BoE Bank Rate | LNG link via Qatar for UK gas bills |

## How the pieces fit together (sketch)

Collectors on a timer (AIS, radar, prices, macro) → timestamped snapshots on disk → estimator
(flow + range) → chain model → small API → front end. Every output carries a receipt (inputs,
their collection times, code version), which the UI shows on click. This splits cleanly into the
lanes proposed in `docs/design.md`.

## Pitch lines to try

- "The strait has gone dark. We turned the lights back on."
- "Ship trackers say 3.5 million barrels a day. Washington says 10. Who's right?" (verify the
  figures first)
- "What a strait on the other side of the world does to your mortgage."

## The 2026 context (check before pitching)

Researched 24 Oct 2026, mostly from search snippets because many sites were unreachable; verify
each claim at its source before it goes on a slide.

- US and Israeli strikes on Iran around 28 Feb 2026; Iran declared the strait closed on 4 Mar; a
  ceasefire was announced 8 Apr; attacks on shipping resumed in July
  ([CRS R45281](https://www.congress.gov/crs-product/R45281),
  [CNBC](https://www.cnbc.com/2026/04/21/oil-price-iran-war-middle-east.html)).
- Flow estimates disagree sharply: Vortexa ~3.5 and Argus ~3.7 mb/d for August against US officials'
  ~10 mb/d ([Argus](https://www.argusmedia.com/es/news-and-insights/latest-market-news/2867794-us-high-balling-hormuz-energy-flows));
  Windward ~8.9 mb/d for 20–22 Sep from satellite ([Windward](https://insights.windward.ai)).
- Kpler, via Gulf News: ~80% of Hormuz traffic runs dark
  ([Gulf News](https://gulfnews.com/world/mena/80-of-hormuz-traffic-goes-dark-and-keeps-oil-prices-in-check-1.500649281)).
  Windward: 61.2% of logged August transits were false because of spoofing.
- Brent: $71.32 (27 Feb) → ~$120 (9 Mar) → ~$107 mid-Sep (secondary source).
- Pre-war baseline: EIA puts Hormuz at 20 mb/d in 2024, ~20% of world petroleum liquids
  consumption ([EIA](https://www.eia.gov/todayinenergy/detail.php?id=65504)); ~20% of global LNG
  trade also passes through.

**What this means for us:** "how much oil really flows" is a live, contested question right now,
so the pitch writes itself. It also means AIS alone undercounts badly, and the dark-ship estimate
is the product, not a side feature. New feature idea: **us vs the analysts**, our estimate on the
same chart as Vortexa, Argus, Kpler, Windward and the US government figure, each with its date.

## Data

What we found (24 Oct 2026). "Unconfirmed" means we could not check it; treat it as unknown.

| Need | Best option | Access | Catch |
|---|---|---|---|
| Ship counts (baseline) | [IMF PortWatch](https://geo.btaa.org/catalog/957b1c2f-a9b9-436c-a576-f7f3ddb9d736) daily Hormuz transits, tanker counts and DWT since 2019 ([straits.live](https://straits.live/data) mirrors it as CSV/JSON) | Free, no key | ~10-day lag, weekly updates; AIS-visible ships only |
| Ship positions | [GFW AIS presence](https://globalfishingwatch.org/platform-update/global-ais-vessel-presence-dataset/) (all vessel types, hourly) | Free token, instant | 72–96 h lag; CC BY-NC 4.0; Gulf coverage unconfirmed |
| Live AIS | AISStream.io | Free key | **Sees nothing in Hormuz**: no receivers there ([tracker test](https://github.com/yasumorishima/hormuz-ship-tracker)). Paid feeds (Kpler/Spire) are enterprise-only |
| Dark ships | [GFW SAR detections](https://pmc.ncbi.nlm.nih.gov/articles/PMC10764273), each flagged matched or unmatched to AIS | Same GFW token | ~5-day lag; Hormuz footprints unconfirmed |
| Raw radar | Sentinel-1 via [Copernicus Data Space](https://dataspace.copernicus.eu/) | Free account | 1–3 day revisit at this latitude (unconfirmed); we run detection ourselves |
| Sanctioned tankers | [OpenSanctions maritime](https://www.opensanctions.org/datasets/maritime/) (19k vessels by IMO); [OFAC SDN](https://sanctionslist.ofac.treas.gov/Home/static/sdn.html) as public-domain backup | Free download | OpenSanctions is CC BY-NC 4.0 |
| Oil prices | EIA API v2: `RBRTE` (Brent), `RWTC` (WTI), `EMM_EPMRR_PTE_NUS_DPG` (weekly US gasoline) | Free key by email | 5,000 rows per call |
| US macro | FRED: `DFF`, `CPIAUCSL`, `CPIENGSL`, `MORTGAGE30US`, `GASREGW` | Free key, instant | CPI for Oct 2025 is missing (shutdown) |
| Market view of the Fed | Kalshi public market data (no key); Polymarket Gamma API (no key) | Free reads | Display terms not checked. CME FedWatch has no free API |
| Bypass pipelines | Saudi East–West ~5–7 mb/d; UAE Habshan–Fujairah 1.5–1.8 mb/d ([ENR](https://www.enr.com/articles/62677-hormuz-bypass-infrastructure-was-sized-for-a-short-disruption-this-is-not-that)) | Published figures | Sources disagree; show the range |
| UK (optional) | ONS CPI `D7G7`; BoE Bank Rate `IUDBEDR`; [Fuel Finder](https://www.gov.uk/guidance/access-the-latest-fuel-prices-and-forecourt-data-via-api-or-email) pump prices | Free; Fuel Finder needs OAuth | ONS API route unconfirmed |

**Backtest events:** Abqaiq attack, 14 Sep 2019: Brent +12.7% on 16 Sep, the largest daily move in
29 years ([EIA](https://www.eia.gov/todayinenergy/detail.php?id=42675)). Gulf of Oman tanker
attacks, 13 Jun 2019: up to +4.5% intraday, closed ~+1.8%. Red Sea, Nov 2023 onwards: Bab
el-Mandeb oil fell from 8.7 to 4.0 mb/d, with a muted price effect
([EIA](https://www.eia.gov/todayinenergy/detail.php?id=63446)). The 2026 crisis is the obvious
main case.

**Weekend stack:** PortWatch for the baseline, GFW AIS + GFW SAR (unmatched detections) for the
dark-ship signal, one hand-picked Sentinel-1 scene as the showcase, EIA + FRED for prices and
macro, Kalshi for the market's Fed view, OpenSanctions for flags.

**Biggest risk:** no free live AIS in Hormuz, and what AIS exists is spoofed. So the demo is
"near-live": every view says how old its data is, and nothing is labelled live unless it is.
GFW and OpenSanctions are non-commercial licences; fine for a hackathon, say so on screen.
