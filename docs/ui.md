# UI: context for anyone building the front end

Draft. What the product does is in `docs/design.md`; the story the demo has to tell is in
`docs/pitch.md`. Stack: TODO.

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
- Status badge on each data item: **live**, **cached (date)**, **synthetic** or **modelled**.
  Cached data never gets the live badge.
- Estimates show a range, not just one number.
- Works on a laptop projector for the demo first; phone layout is a nice-to-have.

## Open questions

- Map library and tile source (licence and offline fallback for the demo venue's Wi-Fi).
- Which cost-of-living measures to show (petrol, energy bill, mortgage payment, CPI basket).
