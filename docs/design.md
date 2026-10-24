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

Who has the problem and what they decide: TODO (pick one for the demo, e.g. an analyst or
journalist judging how serious a disruption is, or a household asking what it means for them).

## 2. User

TODO: who uses it, when, and what they see. Working assumption: someone watching a supply shock
unfold who wants "how much oil is actually getting through, and what does that do to rates and
prices". UI detail lives in `docs/ui.md`.

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

Open questions: how to validate the hidden-ship estimate; which historical shocks to fit the
chain on; US-only or also UK.

## 5. Demo

TODO, sketch in `docs/pitch.md`: live map of Hormuz, the flow number with seen vs. hidden, then a
"what if flow drops by X%" slider rippling through price, rates and cost of living.

## 6. Lanes

TODO: one per human. Natural split: (a) ship data and flow estimate, (b) economic knock-on model,
(c) UI and demo, (d) pitch, data provenance and validation.

## 7. Risks and cuts

- Live AIS for the Gulf may be unavailable or paid. Fallback: a recorded slice of real AIS, shown
  as cached with its date.
- The hidden-ship estimate may be hard to validate in a weekend. Cut to "seen flow vs. published
  baseline" and show the gap.
- The economic chain can sprawl. Cut to oil price → CPI → Fed rate first; cost of living last.
