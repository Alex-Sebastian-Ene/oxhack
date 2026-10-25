# Pitch: context for anyone writing slides, the video or the demo script

The product itself is in `docs/design.md`; the screens are in `docs/ui.md`. Judging criteria and time
limits go in `Context/event-rules.md`; the organisers had not published them in anything we found by 25 Oct
2026, so ask at the event.

## The hook we have now (verify first)

Hormuz is in the news: Iran declared the strait closed in March 2026, and published estimates of
what still gets through disagree by about three times (trackers ~3.5 mb/d, US officials ~10 mb/d),
with most traffic reportedly running dark. Sources and caveats are in `docs/ideas.md`. A five-moment
storyboard is on the design canvas (board Q) and in the "Demo moments" list in `docs/ideas.md`.

## The story in one breath

Oil runs through everything: fuel, food, inflation, interest rates, the cost of living. Much of
the world's seaborne oil passes through one narrow strait, Hormuz, and some of the tankers there
are ghosts: transponders off, positions faked. We watch the strait from space, estimate how much oil is
really getting through, and show what a change in that flow means for the Fed's rates and for
people's bills.

## The pitch, start to finish (about three minutes spoken)

Numbers are as of 25 Oct 2026, from `docs/ideas.md`, `docs/strait-live-data.md`, `docs/chain.md` and
`notes/`. The 2026 market figures came from secondary sources: check each at its source before it goes on a
slide (rule below).

**1. Why it matters (30 s).** In March 2026 Iran declared the Strait of Hormuz closed. Before the war about
20 million barrels of oil a day went through it: about a quarter of all oil shipped by sea, a fifth of what the
world uses (EIA). Brent, the world's benchmark oil price, went from $71 to about $120 in ten days. And nobody
agrees how much still gets through: for August, Vortexa and Argus said about 3.5 million barrels a day, US
officials about 10. Kpler reckons 80% of the traffic runs dark.

**2. The problem (20 s).** Ship trackers only see ships that want to be seen. Tankers switch their transponders
off or fake their positions, so the flow everyone starts from is wrong, and every forecast built on it (oil
prices, inflation, interest rates, our bills) inherits the error.

**3. What we built (20 s).** Hormuz Flow follows the oil from the water to the wallet. One page, one slider:
how much flow is lost, what that does to the oil price, to inflation and rates, and to the cost of living in
175 countries. Every number says where it came from and when, and every estimate comes with its range.

**4. How it works (90 s): which data, which model, what it gives.**
- *Counting the ships.* IMF PortWatch (built with the University of Oxford) gives daily ship counts through the
  strait; Global Fishing Watch gives ship signals (AIS) and radar detections from the European Space Agency's
  Sentinel-1 satellites. Our estimator adds three things: tankers seen crossing, tankers that went dark
  mid-crossing, and tankers never on AIS at all, counted from radar with Little's law. 4,000 Monte Carlo draws
  give a 90% range. On simulated traffic where we know the truth, the range caught it 60 times out of 60; AIS
  alone saw under half of it.
- *From barrels to Brent.* The IEA's monthly count of lost flow and daily Brent give how much Brent rises per
  point of lost flow over the 2026 closure: about half a percent per point. It passes a test on a crisis it
  never saw, the 2023–24 Red Sea disruption. Brent's own swings come from a GARCH model with heavy-tailed Lévy
  jumps, fitted on daily prices since 1987.
- *From Brent to people.* A Bayesian model and two neural networks, trained on 25 years of US, UK and
  euro-area data (FRED, the ONS, Eurostat, EIA fuel stocks, PortWatch flows), forecast inflation,
  unemployment, interest rates and 13 industry costs with 90% bands. Fitted only on data from before the
  closure and given the real oil price, 89% of what actually happened fell inside those bands. For every
  country, UN Comtrade says how much of its oil came from the Gulf, and IMF and UN FAO price data drive a
  cross-country model of groceries, energy and transport.
- *Gemini* turns our numbers into plain language, and may only cite our facts.

**5. Why trust it, and why us (20 s).** Our inflation forecasts beat the Cleveland Fed's model and the Michigan
survey; professional forecasters still beat us, and the app says so. The paid trackers sell flows to traders.
We go from the ships to the bills, free, in one page that works offline.

**6. Close (10 s).** "The strait is closing. Follow the oil." Then the live site:
https://alex-sebastian-ene.github.io/oxhack/

**Say carefully.** The World view's prices run on the IEA's count of lost flow; our dark-ship estimate sits
beside it, "for comparison only", because the strait map plays a simulation calibrated to published figures
(the collectors for real data are built). Don't call anything live.

### Which data feeds which model, and what it gives (a slide)

| Step | Data (who publishes it) | Model | Output in the app |
|---|---|---|---|
| Ships in the strait | Daily transits: IMF PortWatch (IMF, University of Oxford). AIS positions and radar detections: Global Fishing Watch, ESA Sentinel-1 (Copernicus). Identities: ship registries, OFAC and OpenSanctions | Gate crossings + bridged AIS gaps + radar with Little's law; Monte Carlo over load, recall and speed; ghost score | Barrels a day, seen and hidden, with a 90% range; each ship's ghost score (Strait view) |
| Lost flow → Brent | Lost flow: IEA monthly figures. Brent: EIA via FRED. Other chokepoints: PortWatch | Event study of the 2026 closure, placebo band from 2019–25, Red Sea 2023–24 as the out-of-sample check | Brent for any loss, with its range (the shock card, step 2) |
| Brent's swings | Daily Brent since 1987 (EIA via FRED) | GARCH volatility with Lévy (CGMY) jumps | 12-month Brent paths that carry the uncertainty on |
| Knock-ons | US: FRED (BLS, the Fed, EIA). UK: ONS. Euro area: Eurostat. Fuel stocks: EIA. Supply chains: NY Fed. Flows: PortWatch | Bayesian pass-through (MCMC) + two neural networks, an equal-weight ensemble | Inflation, unemployment, policy rates and 13 industry costs with 90% bands (step 3, Economy tab) |
| Emergency stocks | IEA releases and stocks held; national stock data | The price premium per barrel still missing after releases | How long each country's stocks last (step 1, the country card) |
| Every country | Oil imports by partner: UN Comtrade. Prices: IMF and UN FAO (FAOSTAT). Trade: World Bank. Pump prices: national sources | Gulf share × lost flow; each country's own fuel pass-through; gradient-boosted trees with a median regression (the naive rule where that didn't win) | Oil cut off, fuel cost and cost of living by item for about 190 countries (map, country card) |
| Households | US: BLS. UK: ONS, including its Household Costs Indices. Euro area: Eurostat | The basket-item model (Bayesian, item by item), weighted by each group's spending | Real pay against bills; each UK household group's costs (Households view) |
| Industries and products | Cost shares: IATA, CIBC, ATRI and others (Eileen's `notes/industry/`). Producers: worldsteel, USGS, IEA | Share of costs × price move; regression links for steel and aluminium | What a product's price move costs its buyers (Product card, Industries tab) |
| Plain-language panels | Only the facts above | Gemini, written ahead and labelled with its model and date | "What is it?" and "Summarise with Gemini" |

## Beats

1. **Hook.** One chokepoint, a big share of the world's oil, and part of it invisible. (Use a
   cited figure for the share, e.g. from EIA, with its year.)
2. **Problem.** Ship trackers only see ships that want to be seen. Ghost tankers mean the visible
   flow is wrong, and everything downstream (prices, inflation, rates) is guessed from it.
3. **What we built.** Live view of Hormuz; an estimate of real flow, split into seen and hidden,
   with an uncertainty band; and a chain from flow to oil price, inflation, the Fed rate and the
   cost of living.
4. **Demo moment.** Drag "flow through Hormuz" down and watch petrol, inflation, the expected rate
   and a household's monthly costs move, each with its source.
5. **Why trust it.** Every number shows where it came from and when. Estimates show their range.
   Anything synthetic or cached is labelled.
6. **Who it's for / what's next.** Several users, one chain (`docs/design.md`, sections 1 and 2): energy
   analysts and traders, journalists, policymakers, aid and government planners, businesses with
   oil-linked costs, and households. Lead with one framing (below) and name the others in a line.
   What's next:
   - switch the strait map from its calibrated simulation to real observations (the collectors in
     `experiments/strait_sources.py` are built; they need a network that reaches GFW and Copernicus);
   - more chokepoints (Bab el-Mandeb is in; Suez, Malacca and Panama next);
   - household groups beyond the UK, and alerts when the estimate moves;
   - Gemini pictures for each resource once the key has image quota (`bake --images` is wired).

## Framings, one line each

- **The analyst's instrument:** the flow figures disagree by 3x; we count the ships nobody else counts,
  show our range, and follow it to prices.
- **The policymaker's dashboard:** one slider from the strait to inflation, emergency stocks and the
  countries hit hardest, with every model tested against the experts.
- **The household's translator:** what a closed strait does to your groceries, energy and transport,
  country by country, with a source for every number.
- **The open public good:** what paid terminals sell to traders, free, offline in one file, and honest
  about what it doesn't know.

## Rules for pitch material

- Same provenance rule as the app: every number on a slide cites a source and date.
- Don't claim live data in the video unless it was live when recorded; say "recorded on <date>".
- "Ghost ships" is the hook word; also say "dark fleet / AIS switched off" once so experts follow.

## Decided (swap in Linear if the team prefers)

- **Audience framing:** start global (the strait, the flow figures that disagree, Brent and inflation) and
  land local (one country's groceries and bills, a UK household group). The framings above let the
  speaker lean towards whoever is judging.
- **The example shock:** the 2026 closure as the IEA counts it (89 points of normal flow lost in March,
  47 by September), with the 2023–24 Red Sea disruption as the check on the price link.
