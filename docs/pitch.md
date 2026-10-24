# Pitch: context for anyone writing slides, the video or the demo script

Draft. The product itself is in `docs/design.md`; the screens are in `docs/ui.md`. Judging
criteria and time limits go in `Context/event-rules.md` once we have them (TODO).

## The story in one breath

Oil runs through everything: fuel, food, inflation, interest rates, the cost of living. Much of
the world's seaborne oil passes through one narrow strait, Hormuz, and some of the tankers there
are ghosts: transponders off, positions faked. We watch the strait live, estimate how much oil is
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
6. **Who it's for / what's next.** TODO once section 1 of `docs/design.md` names the user.

## Rules for pitch material

- Same provenance rule as the app: every number on a slide cites a source and date.
- Don't claim live data in the video unless it was live when recorded; say "recorded on <date>".
- "Ghost ships" is the hook word; also say "dark fleet / AIS switched off" once so experts follow.

## Open questions

- Audience framing: global (Fed and oil markets) or local (a UK or US household)?
- Which real event do we replay as the example shock?
