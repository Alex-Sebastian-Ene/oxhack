# Hormuz Flow: industry view (Eileen's copy)

Edward's strait page with his materials globe built in, aimed at industry users: which products an
oil shock reaches, which countries make and ship them, and what it does to their price.
Open `index.html` in a browser; it needs no server. It is the same page as the shared artifact
<https://claude.ai/artifact/84rJe1aD8Vpe7KvAnq8a39> (version 32).

## What it shows

- **Strait view:** Edward's strait map. Ship positions are **simulated**. The side cards show **real**
  IMF PortWatch transit counts and tanker capacity for Hormuz (`chokepoint6`), cached to 18 Oct 2026
  and collected 2026-10-24. Click a ship to pause the replay and see its card.
  The side panel leads with the flow estimate in one line (what AIS shows, our estimate, what never appears on
  AIS) and the scenario it comes from; every number has a label; PortWatch cards are tagged **Real data** and the
  map **Simulated ships**. "What this means" carries the lost flow to the World view's Brent price, and the
  published-estimates chart shows when each figure refers to, with "Ours" marked as simulated.
- **World view:** one shared state drawn as a flat map or a 3D globe.
  - **Exposure** (no product picked): each country's exposure to the shock, with the tanker routes out of
    Hormuz in yellow, blinking where they land.
  - **Products** (steel, jet fuel, aluminium, fertiliser, plastic): who makes or ships each one, in its own
    colour. Gulf producers that ship through Hormuz have an amber outline. Pick one from the icons or the
    search at the top.
  - **Click a country:** it floats with a flag tag, a short pop-up gives the main numbers, and the right
    panel has the full analysis in three tabs: Overview (key numbers and the fuel-cost chart), Industries
    (cost impact by industry) and Trade (what it makes, where its inputs come from and where it ships).
  - **Each country's own numbers** (`notes/country-oil.json` from `experiments/country_oil.py`, read by
    `src/patch_countryoil.py`):
    - **Import dependence and the Gulf share** of its oil imports come from UN Comtrade (crude and refined
      products, by value). The Gulf share is an upper bound for oil through the strait: Yanbu and Fujairah
      bypass it. Where Comtrade has nothing (Taiwan, Iran), the hand-entered table (EIA, Energy Institute)
      fills in. A country in neither is grey and says "not in our data".
    - **Fuel cost** uses the country's own Brent to pump-price pass-through, fitted on its motor-fuel prices
      (Europe, Türkiye, the US), or the median of those, marked "pooled". The Industries tab and the fuel-cost
      path use the same pass-through.
    - **Oil cut off** replaces the hand-set exposure score: an importer's Gulf share of oil imports × the share of
      Hormuz flow lost, a Gulf producer's exports trapped, another exporter's oil earnings. It colours the map and
      orders "Most oil cut off". It misses Gulf crude that arrives as fuel refined elsewhere (Australia's petrol
      from Singapore and Korea).
    - **Cost of living tab** (first in the country panel): prices and food prices now and in Feb 2026, before the
      closure (FAOSTAT, 206 countries), then what 100 spent today costs after 1, 2, 3, 6 and 12 months, with a
      chart. Groceries and all prices use the latest 12 months' rate plus Brent's known moves through the
      country's oil link: our cost-of-living model's link, ridge-updated on the country's own prices. The range
      is the country's own past misses of that rule (2015-2024). A fitted time-series model lost to the rule in
      backtests and isn't used. The US, UK and euro area also get the item basket (bread, dairy, meat, fruit and
      vegetables, energy, eating out) from Seb's cost-of-living model.
    - **The pop-up** leads with groceries in 12 months, fuel and oil cut off, then prices now and our models'
      12-month what-ifs: consumer prices (the Bayesian model: US, UK, euro area) and factory prices (the sector
      model: Europe, Türkiye, the US).
  - **Industries tab:** five hand-picked industries per country (illustrative), then **Add an industry**:
    - any of the page's 16 oil-exposed industries, drawn the same way as the hand-picked ones;
    - any of the 20 industries in Seb's sector model (`notes/country-trends.json`): its producer prices after
      12 months at the shock card's Brent, its latest index and year-on-year change, and its forecast skill.
      Cement, chemicals, plastics and manufacturing also show their energy or materials share from
      `notes/industry/industry_exposure.csv`. Outside Europe, Türkiye and the US these say "no data".
    - Added industries stay as you click between countries. Rows with a sector series link to its chart in
      the Trends tab (`src/patch_pickind.py`).
  - **Trade tab:** every country's exports and imports of goods and services (US$ and % of GDP), the trade
    balance, goods exports and imports, fuel's share of each, and its five largest buyers and suppliers of goods
    (a partner on the map opens its own card). Each figure is the latest year published, shown with its year;
    countries the sources don't cover (Taiwan, Northern Cyprus, Somaliland and a few others) say so.
  - **Economy tab:** how consumer prices and unemployment respond over 36 months at the slider's Brent price,
    for the US, the UK or the euro area (a euro-area country shows euro-area figures; other countries can compare
    the three). Unemployment is drawn in grey and labelled "No reliable effect": its historical link with oil has
    the demand sign, so the what-if keeps it at zero (`docs/macro-ensemble.md`).
  - **Trends tab:** the country's prices over time, for 37 European countries, Georgia, Kosovo and the US.
    - **How well we forecast it:** the industry model's forecast error against a naive forecast, for the
      country's producer prices and output.
    - **Consumer prices:** annual inflation from 2007, all items against food, motor fuels, electricity or gas.
    - **One industry at a time:** its producer price index from 2007, the extra change the industry model gives
      it over 12 months at the shock card's Brent price, and its output index. Output is history only, because
      oil doesn't move output reliably in the tests.
    - **Other countries:** the tab says they aren't covered. The UK has all-items inflation only (ONS).
- **The shock card** sits under the country card and reads as three steps: what the scenario sets, the Brent price
  you choose (with $70 / $109 / $140 quick prices), and what follows, with a plain-English sentence.

## Why these numbers? (Gemini explains, off by default)

The country card's Overview tab and the product card can ask Gemini to explain their numbers in plain words.

- **What Gemini gets:** only the numbers that box shows, each with its source, numbered. That's the scenario and
  Brent setting, then exposure, fuel cost, the Hormuz share, industry costs, the price link and its band, the top
  producers and the cost to buyers.
- **What it returns:** 3 to 5 bullets that follow the chain from Hormuz flow to Brent to price to who pays, and say
  what is uncertain. Each bullet lists the facts it used, as `[1][3]`.
- **The check:** `explain_server.py` compares every number in every bullet with the facts that bullet cites. Any
  number not in them is shown in red as "Not in our data". The facts sent are listed under the answer.
- **The label:** "AI-written by {model}", with its time, "cached" when it is, and "not checked by the team". Gemini
  never changes a number, a colour or a table.
- **Quota:** it uses no Google Search tool, so it runs on the plain free-tier quota. The same question is cached in
  `data/raw/explain/` (git-ignored).

To run it, put `GEMINI_API_KEY=your-key` in the repo's `.env` (git-ignored, the same file Edward's brief proxy
reads), or set it in the shell. Then:

```powershell
uv run ui/industry/explain_server.py
```

Then open `ui/industry/index.html?explain=1`, or `?explain=<url>` for a service elsewhere.

- **Origins:** the service answers only pages from disk or localhost. A deployment adds its address in
  `EXPLAIN_ORIGINS`.
- **Model:** `GEMINI_MODEL`, default `gemini-3.8-flash`.
- **Port:** the service refuses to start if its port (8789, or `EXPLAIN_PORT`) is taken.

Offline tests: `uv run --no-project --with pytest pytest -q tests/test_explain_server.py`.

## The model behind the numbers

The page runs on Seb's recommended chain (`docs/chain.md`). **You set the lost Hormuz flow** (0 to 100 points of the
pre-war 20 mb/d, as the IEA counts it) in The shock card; the scenario menu sets its starting value: the 2026 closure
preset below for the 2026 scenarios, 0 for pre-war. Edward's estimate of the true flow is shown beside it for comparison
only, because its ships are simulated. Everything else follows:

- **Brent:** pre-war $70 times Seb's flow-premium curve per point of the IEA's lost strait flow
  (`notes/flow-premium-iea.csv`, OXH-9), averaged over the next 252 trading days, with its 90% band. At 82 points
  held for 12 months that is about $106 ($75 to $204), harsher than 2026 was.
- **The 2026 closure preset** (`patch_iea.py`) is not a point on the slider. It is the chain replayed on 2026 as the IEA
  counts it (`notes/chain-scenarios-2026-3m-margins.csv`: 89 points lost in March to 47 in September, later months
  holding the last), with Brent from the same curve over that path: about $95 ($75 to $145). The slider shows the
  path's March–October average, 67 points, and its mark sits there.
- **Jet fuel, nitrogen fertiliser, plastics resin, diesel at the pump, CPI and unemployment (US, UK, euro area):**
  the chain's scenario table (`notes/chain-scenarios-3m-margins.csv`: bayes_own + global_lin + global, with the
  margin member on fuels), straight lines between its 0/25/50/82/100-point rows. Shown as the extra change against
  no disruption, with the table's 90% range of outcomes. Unemployment is shown grey: Seb marks it forecast only.
- **Steel and aluminium, energy bills, country fuel costs:** Seb's linear Brent links (OXH-5, `notes/oil-chain-links.md`),
  at the Brent price above.
- **Emergency oil stocks** (`patch_reserves.py`, Seb's `experiments/reserves.py`, `notes/reserves.md`): under the slider,
  choose No release, As in 2026 (the default: every number above is unchanged) or Maximum (the IEA's maximum drawdown,
  up to 25 mb/d for two months, until the 1.8 bn barrels held for release run out). Brent follows the flow-premium
  curve restated per barrel still missing after releases (`notes/reserve-scenarios.csv`). That file is still on the
  older PortWatch-trough curve, so until `reserves.py` is restated the page keeps each policy's premium ratio to the
  2026 releases and applies it to the IEA curve. The chain's numbers are
  the table above plus the policy's difference in the chain's own replays under each policy
  (`notes/chain-scenarios-3m-d2000-margins*.csv`). The release line is tagged "assumed": the premium is taken to
  scale with the barrels still missing, which one closure cannot test.
- **Oil stocks by country:** the country card and pop-up show each country's stocks in its source's unit (IEA days
  of net imports for members, our JODI calculation of days of demand for Taiwan, Thailand, India and the
  Philippines, the EIA estimate for China, an official claim for Pakistan; `notes/reserves/country-cover.csv`), and
  for importers how long they would replace the lost Hormuz oil at the slider's setting.

**Not from a model, labelled "illustrative" on the page** (asked on OXH-3, 25 Oct 2026):

- **The exposure score** (map colours, "Most exposed"): a hand-written formula from the original Hormuz Flow page.
  Its inputs are cited; its weights (0.4 / 0.6 for importers, ÷3, +0.15 and ×60 for exporters) are not.
- **The 12-month fuel-cost path:** the country's fuel cost, decayed at hand-set recovery speeds.

**Fuel cost in a disruption** (`src/patch_disruption.py`) is no longer hand-set. The old shortage premium
(`0.8 × share of flow missing × share of oil via Hormuz`) is replaced by Seb's cost-of-living model (OXH-3): in a
supply disruption retail fuel moves 1.49 times its normal Brent link (90% interval 1.08 to 1.89), pooled over the US,
UK and euro area and assumed for other countries. It applies to the country card, the exposure score, the fuel-cost
path (fading as the flow recovers) and the Industries tab, whose ranges use the interval.

## Where the numbers come from

Everything is a cached snapshot bundled into the page. Nothing is fetched live.

| Number | Source | Collected |
|---|---|---|
| Ship transits and tanker capacity | IMF PortWatch `Daily_Chokepoints_Data`, `chokepoint6` | 2026-10-24 (data to 2026-10-18) |
| Producers, exporters, inputs, trade flows | Edward's `ui/globe/data/materials.js` (from `notes/materials/`) | 2026-10-24 |
| Jet fuel, fertiliser, plastic price moves | Seb's Bayesian pass-through, `notes/macro-bayes-responses.csv` (commit `6d6c83e`) | FRED, 2026-10-24 |
| Steel, aluminium price moves | Seb's linear links, `notes/steel-aluminium-responses.csv` (on main via PR #19; first posted on OXH-5) | FRED, 2026-10-24 |
| Petrol, energy CPI, headline CPI steps | `notes/oil-chain-links.md` | FRED, see that note |
| Economy tab: CPI and unemployment paths, US / UK / euro area | Seb's Bayesian responses, `notes/macro-bayes-responses.csv` (`experiments/macro_bayes.py`), read by `src/patch_economy.py` at build time | FRED/ONS/Eurostat to 2026-10, generated 2026-10-24 |
| Cost to buyers | `notes/industry/`: airlines 31.4% fuel share (IATA), farming 40% fertiliser share (CIBC) | see that folder |
| Trade tab: exports and imports, goods, fuel shares, main partners | `notes/trade-stats.json` (`experiments/trade_stats.py`): World Bank WDI (`NE.EXP/IMP.GNFS.CD` and `.ZS`, `TX/TM.VAL.MRCH.CD.WT`, `TX/TM.VAL.FUEL.ZS.UN`), UN Comtrade public preview (partners, all goods). Read by `src/patch_tradestats.py` at build time | 2026-10-25 (WDI updated 2026-10-08) |
| Trends tab: inflation, industry prices and output, forecast skill, oil effect by industry | `notes/country-trends.json` (`experiments/country_trends.py`): Eurostat HICP, `sts_inppd_m` and `sts_inpr_m`; BLS CPI and PPIs, Fed industrial production and ONS CPI. Skill and oil effects are `global_lin`'s in the sector run (`notes/sector-global-results.md`). Read by `src/patch_trends.py` at build time | Eurostat and FRED, 2026-10-24/25 |

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
