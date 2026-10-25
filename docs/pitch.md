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
