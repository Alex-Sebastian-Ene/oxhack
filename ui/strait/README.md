# Hormuz Flow map

A zoomable, animated map of tankers crossing the Strait of Hormuz, with the estimate of oil really
moving through it. Open `index.html` directly in a browser; no server or network needed.

The ships are **simulated**, calibrated to published flow figures, because no free live feed covers
Hormuz. Why, and how the estimate works: `docs/strait-live-data.md`.

| File | Made by |
|---|---|
| `data/geo.json` | `uv run experiments/strait_geo.py` (coastline, lanes, gate) |
| `data/scenarios.js` | `uv run experiments/strait_flow.py` (ships and estimates for each scenario) |
| `index.html`, `style.css`, `app.js` | by hand |

One-file build for sharing or publishing: `uv run experiments/strait_bundle.py hormuz-flow.html`
(add `--fragment` for hosts that wrap the page in their own `<html>`).
