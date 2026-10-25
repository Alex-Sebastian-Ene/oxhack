# UI: context for anyone building the front end

What the product does is in `docs/design.md`; the story the demo has to tell is in `docs/pitch.md`. Stack:
one self-contained HTML page (`ui/app/index.html`) in plain JavaScript and CSS, no framework, built by
`ui/app/src/build.py` from Eileen's industry page plus the layers in `ui/app/src/` (`ui/app/README.md` lists
them). Maps and charts: D3 7.9 and TopoJSON on Natural Earth; the 3D globe: globe.gl. Pixel art and sound are
made in code. Data from the Python pipeline in `experiments/` is inlined at build time, so the page needs no
server and no network, and the same file is published as a claude.ai artifact.

Sketches of every screen below, plus the dynamic features (live pulse, receipts, judge mode,
satellite swipe, us vs the analysts and more), are on the design canvas; `docs/ideas.md` lists
them by letter.

## Screens

1. **Strait map.** Live map of Hormuz and its approaches. Tankers we see on AIS, plus markers for
   estimated hidden ships (AIS gaps, satellite detections with no AIS match) drawn differently,
   e.g. hollow or dashed. Click a ship for its size, laden state and why we flagged it.
2. **Flow panel.** Estimated barrels per day through the strait: seen, estimated hidden, and the
   total with an uncertainty band, next to the published baseline. A small trend over recent days.
3. **Knock-on chain.** Flow → oil price → inflation → Fed rate → cost of living, shown as a chain
   of linked cards or a flow diagram. Each card: current value, modelled change, source and date.
4. **What-if.** A slider for "flow through Hormuz" (e.g. −50% to +10%) that updates the chain
   live. Make it obvious when the screen shows a scenario rather than the current estimate.

## Rules every screen follows

- Every number has a source and a timestamp next to it or one tap away.
- Free AIS lags in Hormuz, so the header says how old the positions are ("near-live, N h old"),
  never just "live".
- Status badge on each data item: **live**, **cached (date)**, **synthetic** or **modelled**.
  Cached data never gets the live badge.
- Estimates show a range, not just one number.
- Works on a laptop projector for the demo first; phone layout is a nice-to-have.

## As built

- Strait map (screen 1) and flow panel (2): the Strait view, with seen and dark ships, each ship's card, the
  estimate's 90% range and real PortWatch counts; the header's FLOW readout.
- Knock-on chain (3) and what-if (4): "The shock" card on the World view, in four steps (lost flow, Brent,
  the next 12 months, households), with presets for the 2026 closure, half and shut.
- Added since: the World map's exposure, materials and countries, the Product and country cards, the
  Households view and the Models view.

## Decided

- **Map library and tiles:** D3 and TopoJSON on Natural Earth for the flat map, globe.gl for the globe, all
  bundled into the page, so the demo needs no Wi-Fi (licences in `ui/app/vendor/`).
- **Cost-of-living measures:** US diesel at the pump, energy bills and overall inflation in the shock card;
  for every country groceries, housing and energy, transport and all prices; the UK and euro area by basket
  item; UK household groups on the Households view, mortgage holders among them. There is no mortgage-payment
  figure: holding the 10-year yield, the Fed's rate has no direct effect on mortgage rates
  (`docs/knock-on-validation.md`).
