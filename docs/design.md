# OxHack26 design

Shared context for every coding session. The pitch is in `docs/pitch.md`, the UI in `docs/ui.md`.
Keep it short; lanes in `coord/PROTOCOL.md` come from section 6.

**One line:** estimate how much oil is really flowing through the Strait of Hormuz from live ship
data, including the "ghost" tankers that hide, then follow a change in that flow through to oil
prices, the Fed's interest rate and the cost of living.

## 1. Problem

Oil drives a chain of things people feel: fuel and energy prices, inflation, the interest rate the
Fed sets, and from there mortgages, rents and the cost of living. The chain starts with how much
oil is physically moving, and that number is murky. A large share of the world's seaborne crude
passes through the Strait of Hormuz, and some tankers (the "ghost" or "dark" fleet) switch off or
spoof their AIS transponders, so the flow you can see on a ship tracker is not the flow there is.

Who has the problem, and what they decide with a better number:

- **Energy and commodity analysts, traders:** how much oil is really getting through, and whether the price
  is over- or under-reacting. Published flow figures for August 2026 differ by about 3x (Vortexa ~3.5 mb/d,
  US officials ~10 mb/d; `docs/ideas.md`), so a range with its method beats picking one.
- **Journalists and fact-checkers:** which of the conflicting figures is plausible, and what the shock means
  for readers' bills, with a source for every number they quote.
- **Policymakers, central-bank watchers:** how much inflation the shock adds and for how long; whether
  releasing emergency stocks covers the gap, and for how many days; which countries are hit hardest.
- **Governments of importing countries, aid and development organisations:** which countries lose most of
  their oil and what that does to food and fuel prices there, to decide where help goes first.
- **Businesses with oil-linked costs** (airlines, freight, farming, plastics and packaging, construction):
  what a product's price move does to their costs and how fast it arrives, to plan prices, hedges and stock.
- **Households, students and teachers:** what a strait thousands of miles away does to the price of
  groceries, energy and transport, and why.

## 2. User

Several users, one page. Each starts in a different place and reads a different part of it; the flow
estimate and the chain behind every view are the same. UI detail lives in `docs/ui.md`.

| User | When they open it | What they do | What they see |
|---|---|---|---|
| Energy analyst | A new flow figure or a price spike | Compares the seen and the estimated hidden flow with published figures; moves the lost-flow slider | Strait view (seen vs dark ships, the estimate's 90% range), the shock card's Brent and its range |
| Journalist | Writing up the crisis | Picks a country readers care about; checks each number's source | Country card (cost of living, trade, oil cut off), info keys and Sources buttons, the Gemini profile with its cited facts |
| Policymaker | Deciding on a stock release or a rate path | Sets a scenario (the 2026 closure, half, shut); reads inflation and how long stocks last | The shock card (steps 1 to 4), "Most oil cut off", the Economy tab, the Models view's record against the experts |
| Aid or government planner | Triage across many countries | Ranks countries by oil cut off; opens the worst | "Most oil cut off" with More, each country's cost of living by item (groceries, housing and energy, transport) |
| Business | Pricing or hedging for next year | Picks its product (jet fuel, fertiliser, plastic, steel, aluminium) | The Product card: price in 12 months, who makes and ships it, what it costs buyers and how fast |
| Household, student | Curious, or worried about bills | Drags the slider and watches the numbers move | The landing page, the Households view (pay against bills, UK household groups), the step-3 tiles |

**Framings for the pitch** (pick one to lead with; the others become "and it also serves"):

1. **The analyst's instrument:** "The flow figures disagree by 3x. We count the ships nobody else counts, show
   our range, and follow it to prices."
2. **The policymaker's dashboard:** "One slider from the strait to inflation, emergency stocks and the
   countries hit hardest, with every model tested against the experts."
3. **The household's translator:** "What a closed strait does to your groceries, energy and transport,
   country by country, with a source for every number."
4. **The open public good:** "What paid terminals sell to traders, free, offline in one file, and honest
   about what it doesn't know."

## 3. Data

Every number carries its source and collection time; synthetic is labelled synthetic; cached is
never shown as live (see `AGENTS.md`). The checked version of this table (Gulf coverage, cost,
licence, 2026 context) is in `docs/ideas.md`; the key finding is that **no free live AIS feed
covers Hormuz**, so the app is near-live and says how old each view is.

| Need | Sources (checks in `docs/ideas.md`) | Notes |
|---|---|---|
| Ship positions and counts in and around Hormuz | IMF PortWatch (daily transits); GFW AIS presence (hourly, ~3-day lag) | AISStream has no receivers in Hormuz; paid feeds are enterprise-only |
| Ships with AIS off (ghost / dark fleet) | GFW SAR detections unmatched to AIS; Sentinel-1 via Copernicus | Revisit time is days, not minutes |
| Tanker size to convert ships into barrels | Vessel registry fields in AIS (type, deadweight, draught) | Draught change hints laden vs. ballast |
| Baseline flow through the strait | EIA "World Oil Transit Chokepoints" | Use to sanity-check our estimate |
| Oil prices | EIA API (Brent, WTI daily); FRED | |
| Fed funds rate, CPI, mortgage rates | FRED | |
| Cost of living breakdown | BLS CPI components (US); ONS (UK) if we go UK-facing | |

## 4. Approach

Two stages, each a separate lane-sized piece:

1. **Flow estimate.** Count tankers crossing the strait from AIS, convert each to barrels from its
   size and laden state, then add an estimate for vessels we cannot see: gaps in AIS tracks,
   satellite detections with no matching AIS, and position spoofing. Output: barrels per day with
   an uncertainty band, split into "seen" and "estimated hidden". Baseline to beat: the published
   EIA average.
2. **Knock-on model.** From a change in flow, estimate the move in oil price, then in inflation,
   then the Fed's likely rate response, then cost-of-living measures. Start simple (elasticities
   or regressions on historical shocks, each link cited) rather than one big model. Users can
   also drag the flow to run a "what if". Technical notes: the oil-price distribution model is in
   `docs/oil-price-model.md`, and the tested links (oil → petrol, energy and headline CPI hold up
   out of sample; core CPI, the Fed and mortgages are weak or unstable) are in
   `docs/knock-on-validation.md`.

Answered so far:
- **Validating the hidden-ship estimate:** on simulated traffic where the true flow is known, its 90% range
  held the truth in 60 of 60 runs; AIS alone recovered about 47% of the flow in the 2026 scenarios
  (`docs/strait-live-data.md`). Real observations will be compared with IMF PortWatch counts.
- **Shocks to fit on:** the 2026 closure as the IEA counts it, checked against the 2023–24 Red Sea
  disruption (`notes/flow-events.md`).
- **Which countries:** the US, UK and euro area in depth, and about 190 countries for cost of living from
  IMF and FAOSTAT price indices.

## 5. Demo

About three minutes, on the one-file app (`ui/app/index.html`, works offline) with the claude.ai artifact as
a backup link. The spine is the same for every framing; the stop marked for each user is where to linger.

1. **Landing (15 s):** "The strait is closing. Follow the oil." Three headline numbers with their sources;
   open the valve.
2. **The shock (45 s):** pick the 2026 closure as the IEA counts it (89 points lost in March, 47 by
   September). Brent, US diesel, energy bills and inflation move, each with its range and an info key.
   Drag to "Shut" and back. *Policymaker and household stop here.*
3. **The strait (40 s):** seen ships against dark ones, the estimate with its 90% range, a ghost ship's card
   and why it was flagged; the real PortWatch counts beside it. *Analyst stops here.*
4. **A country (40 s):** "Most oil cut off", then one country: its cost of living by item, trade, and the
   Gemini profile that cites the facts it uses. *Journalist and aid planner stop here.*
5. **A product (20 s):** jet fuel: 31% of airline costs, so a +51% price is about +16% on costs, within weeks.
   *Business stops here.*
6. **Why trust it (20 s):** the Models view: our inflation forecasts beat the Cleveland Fed model and the
   Michigan survey, and lose to professional forecasters (SPF); we say so. Every number shows its source
   and date.

Fallbacks: the page needs no network; if the projector is small, the phone layout works; nothing in the
demo depends on a live feed or a Gemini call (the panels are written ahead).

## 6. Lanes

One per human, as in `coord/PROTOCOL.md` (read off each person's commits; swap in Linear if the humans
agree):

- **Edward:** ship data and the flow estimate (`experiments/strait_flow.py`), the app (`ui/`), the research
  desk, the Gemini panels and the pitch.
- **Seb:** the knock-on model: the oil-price distribution, lost flow to Brent, the oil to petrol, CPI, Fed
  and mortgage links, cost of living by item and by country, emergency stocks, the global and Bayesian
  models and the cluster runs.
- **Eileen:** industry impact: Brent to fuel, freight and materials, to business costs (`notes/industry/`),
  and the integrated industry page the app is built from.
- **Yasmin:** readability and UX: the Households page's story, one standard for info keys, panel layout
  and spacing.

## 7. Risks and cuts

- Live AIS for the Gulf may be unavailable or paid. Fallback: a recorded slice of real AIS, shown
  as cached with its date.
- The hidden-ship estimate may be hard to validate in a weekend. Cut to "seen flow vs. published
  baseline" and show the gap.
- The economic chain can sprawl. Cut to oil price → CPI → Fed rate first; cost of living last.
