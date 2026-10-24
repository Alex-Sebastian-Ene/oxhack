# Hormuz Flow: industry view (Eileen's copy)

Edward's strait page with his materials globe built in, aimed at industry users: which products an
oil shock reaches, which countries make and ship them, and what it does to their price.
Open `index.html` in a browser; it needs no server. It is the same page as the shared artifact
<https://claude.ai/artifact/84rJe1aD8Vpe7KvAnq8a39> (version 20).

## What it shows

- **Strait view:** Edward's strait map. Ship positions are **simulated**. The side cards show **real**
  IMF PortWatch transit counts and tanker capacity for Hormuz (`chokepoint6`), cached to 18 Oct 2026
  and collected 2026-10-24. Click a ship to pause the replay and see its card.
- **World view:** one shared state drawn as a flat map or a 3D globe.
  - **Exposure** (no product picked): each country's exposure to the shock, with the tanker routes out of
    Hormuz in yellow, blinking where they land.
  - **Products** (steel, jet fuel, aluminium, fertiliser, plastic): who makes or ships each one, in its own
    colour. Gulf producers that ship through Hormuz have an amber outline. Pick one from the icons or the
    search at the top.
  - **Click a country:** it floats with a flag tag, a short pop-up gives the main numbers, and the right
    panel has the full analysis in three tabs: Overview (key numbers and the fuel-cost chart), Industries
    (cost impact by industry) and Trade (what it makes, where its inputs come from and where it ships).
  - **Economy tab:** how consumer prices and unemployment respond over 36 months at the slider's Brent price,
    for the US, the UK or the euro area (a euro-area country shows euro-area figures; other countries can compare
    the three). Unemployment is drawn in grey and labelled "No reliable effect": its historical link with oil has
    the demand sign, so the what-if keeps it at zero (`docs/macro-ensemble.md`).
- **The shock card** sits under the country card and reads as three steps: what the scenario sets, the Brent price
  you choose (with $70 / $109 / $140 quick prices), and what follows, with a plain-English sentence.

## Where the numbers come from

Everything is a cached snapshot bundled into the page. Nothing is fetched live.

| Number | Source | Collected |
|---|---|---|
| Ship transits and tanker capacity | IMF PortWatch `Daily_Chokepoints_Data`, `chokepoint6` | 2026-10-24 (data to 2026-10-18) |
| Producers, exporters, inputs, trade flows | Edward's `ui/globe/data/materials.js` (from `notes/materials/`) | 2026-10-24 |
| Jet fuel, fertiliser, plastic price moves | Seb's Bayesian pass-through, `notes/macro-bayes-responses.csv` (commit `b6886cf`) | FRED, 2026-10-24 |
| Steel, aluminium price moves | Seb's linear links, `notes/steel-aluminium-responses.csv` (branch `claude/upbeat-jones-ba5f1a`, commit `e0d122f`, not on main yet), posted on OXH-5 | FRED, 2026-10-24 |
| Petrol, energy CPI, headline CPI steps | `notes/oil-chain-links.md` | FRED, see that note |
| Economy tab: CPI and unemployment paths, US / UK / euro area | Seb's Bayesian responses, `notes/macro-bayes-responses.csv` (`experiments/macro_bayes.py`), read by `src/patch_economy.py` at build time | FRED/ONS/Eurostat to 2026-10, generated 2026-10-24 |
| Cost to buyers | `notes/industry/`: airlines 31.4% fuel share (IATA), farming 40% fertiliser share (CIBC) | see that folder |

- All price moves are 12 months after the move in Brent from $70 pre-war, scaled by ln(1+x)/ln(1.1).
  The bands cover the average effect only; single moves vary more.
- Steel and aluminium are US mill-product prices. They are probably an overestimate for a supply shock,
  and they under-predicted the 2026 closure. The page says so on the product card.
- Buyers with no sourced cost share show "no data".

## Build

```bash
python ui/industry/src/build.py
```

The build needs Python 3 and `node` (for a syntax check). It starts from `src/v8.html`, Edward's strait page
as published on the artifact before these changes, and reads `ui/globe/` for the globe library and data.
Each `patch_*.py` step is a list of exact find-and-replace edits that fails loudly if its target text has moved.

Bundled third-party code: globe.gl 2.41.4 (MIT), flag-icons 7.6.0 (MIT), Natural Earth 1:110m and
1:10m (public domain). d3 7.9.0 and topojson load from cdnjs.
