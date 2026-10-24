# UI sketches

Source of the design canvas "Hormuz Oil Flow UI Sketches" (ask Ed for the link), copied on
24 Oct 2026. These are mockups, not app code: each `*.dc.html` file is one board in the canvas's
own format and expects that editor's runtime (`support.js`), so it will not render on its own.
Use them as a reference for layout, copy and behaviour; `canvas.json` holds the board layout.

Numbers in square brackets (`[X.X] mb/d`) are placeholders. Boards marked synthetic use made-up
demo data. The few real figures (EIA's 20 mb/d pre-war baseline, the 2026 published estimates,
bypass pipeline capacity) come from the research in `docs/ideas.md` and still need checking at
their sources.

| Board | File | What it shows |
|---|---|---|
| A | `Main.dc.html` | Command view: strait map, flow estimate (seen vs hidden), knock-on indicators, alerts |
| B | `Ripple.dc.html` | What-if slider from flow to Brent, pump prices, CPI, the Fed and mortgages (interactive) |
| C | `Ghost.dc.html` | File on one suspected dark tanker: track gap, radar hit, draught change, evidence, verdict |
| D | `Phone.dc.html` | Phone view, "what it means for you", US/UK (interactive) |
| E | `Replay.dc.html` | Replay a past shock and compare the model with what happened |
| F | `Pulse.dc.html` | Live pulse of crossings (animated, synthetic) |
| G | `Receipt.dc.html` | Receipt for a number: inputs, steps, output, how to rerun (interactive) |
| H | `Exposure.dc.html` | Who depends on Hormuz oil (interactive) |
| I | `Analyst.dc.html` | Ask-the-analyst chat, alert rules, morning brief |
| J | `Judge.dc.html` | Judge mode: the room votes from their phones (animated, synthetic votes) |
| K | `Spoof.dc.html` | Spoofing checks and ship-to-ship transfer detection |
| L | `Analysts.dc.html` | Our estimate beside the published 2026 estimates (interactive) |
| M | `Snapshot.dc.html` | One radar snapshot to a flow rate with Little's law (interactive) |
| N | `Network.dc.html` | Shadow-fleet network diagram |
| O | `Headlines.dc.html` | Headlines vs what ships did (interactive) |
| P | `Swipe.dc.html` | Before/after swipe of AIS against radar (interactive) |
| Q | `Storyboard.dc.html` | Three-minute pitch in five moments |
| R | `Closure.dc.html` | Closure simulator using published inputs (interactive) |
| S | `Fan.dc.html` | How uncertainty grows down the chain (interactive) |

Look: dark "ops room", IBM Plex Sans and Mono, blue for ships seen on AIS, amber for oil and hidden
ships, status badges LIVE / NEAR-LIVE / CACHED / SYNTHETIC / MODELLED.
