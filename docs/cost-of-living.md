# Cost of living by basket item

Technical notes for the cost-of-living layer of the knock-on chain in [design.md](design.md). It
builds on the links in [knock-on-validation.md](knock-on-validation.md), the Bayesian pass-through
in [macro-ensemble.md](macro-ensemble.md) and the Brent model in [oil-price-model.md](oil-price-model.md).

| Code | What it does | Output |
|---|---|---|
| `experiments/cost_of_living.py` | Basket data and weights, the event misses, the Bayesian item model, Brent and gas paths, folds, event tests, scenario fans | `runs/col/*.json` (git-ignored) |
| `experiments/cost_of_living_report.py` | Tables from the runs; leaves out any fit whose chains did not converge | `notes/cost-of-living.md`, `notes/cost-of-living-fans.csv`, `notes/cost-of-living-responses.csv` |
| `cluster/iridis/cost_of_living{_env.sh,.slurm}` | Iridis environment and the 11-task array (one fit per task) | |
| `tests/test_cost_of_living.py` | Rest of basket, average link, simulation terms, CRPS, Brent paths | |

## Why item by item

- **Average links miss supply shocks.** The validated oil links are averages over calm months,
  demand-driven moves and supply shocks. In the 2026 Hormuz closure they predicted about half of
  the rise in motor fuel in the UK and euro area.
- **Headline hides offsetting errors.** Over the same months they over-predicted food. US headline
  inflation came out close to the forecast only because the fuel and food errors cancelled. You
  only see that by looking at the items.
- **Supply shocks are not alike.**
  - 2022 was a gas and grain shock: Brent fell 18% from February to December while food and
    household energy surged.
  - 2026 is an oil and refined-products shock: fuel and air fares jumped while food barely moved.
  - So a model that learns "supply shock" from one event has to prove it helps on the other.

The aim is accuracy first. The novelty is in the analysis (which items carry the cost-of-living
hit, by region, and where the standard link breaks), not in exotic modelling. A model feature stays
only if it beats simpler benchmarks out of sample.

## Basket

Twelve kinds of item in each region, plus the rest of the basket and headline (41 series). The
items don't overlap, so their weights add up.

| Kind | US (BLS, seasonally adjusted, via FRED) | UK (ONS, CPI index) | Euro area (Eurostat HICP via FRED) |
|---|---|---|---|
| Bread and cereals | `CUSR0000SAF111` | D7D5 | CP0111 |
| Meat | `CUSR0000SAF112` (includes fish and eggs) | D7D6 | CP0112 |
| Dairy | `CUSR0000SEFJ` | D7D8 (milk, cheese, eggs) | CP0114 |
| Oils and fats | `CUSR0000SEFS` | D7D9 | CP0115 |
| Fruit and vegetables | `CUSR0000SAF113` (one index) | D7DA fruit, D7DB vegetables | CP0116, CP0117 |
| Sugar and sweets | `CUSR0000SEFR` | D7DC | CP0118 |
| Electricity | `CUSR0000SEHF01` | D7DT | CP0451 |
| Household gas | `CUSR0000SEHF02` (piped gas) | D7DU | CP0452 |
| Motor fuel | `CUSR0000SETB01` (gasoline) | D7EC (fuels and lubricants) | CP0722 |
| Air fares | `CUSR0000SETG01` | D7EH | CP0733 |
| Restaurants | `CUSR0000SEFV` (food away from home) | D7EW (restaurants and cafes) | CP1111 |
| Headline | `CPIAUCSL` | D7BT | CP0000 |

- **Weights:**
  - US: BLS relative importance, CPI-U, December 2025. BLS blocks scripted downloads, so these
    were read from the published table on 2026-10-24 and are in the code with that source.
  - UK: ONS CPI weights (CJWB … CJYL), 2026.
  - Euro area: Eurostat `prc_hicp_inw`, 2025.
  - The 11 or 12 items are 18% of the US basket, 26% of the UK's and 30% of the euro area's.
- **Rest of the basket** = (headline − Σ weight × item) / rest weight, each month. The composite
  (weighted items + rest) therefore equals headline exactly in the data. It can only differ from
  a direct headline model in its forecasts, which is what the tests check.
- **Drivers:**
  - Brent: monthly average of the daily FRED `DCOILBRENTEU` series.
  - Gas: Henry Hub, monthly (`MHHNGSP`), for the US; the IMF EU gas price (`PNGASEUUSDM`) for the
    UK and euro area.

## Model

One Bayesian model for all 41 series, on monthly log changes (% of the price level), fitted by
NUTS (2 chains, 500 warm-up, 500 draws):

    y[s,k] = a[k] + season[k, month] + rho[k] y[s-1,k] + E[s,k] (1 + kappa[k] D[s]) + e[s,k]
    E[s,k] = sum_l B[k,l] x[s-l] + sum_l G[k,l] g_r(k)[s-l]
    e[s,k] = sigma[k] exp(phi[k] v[s] + psi[k] D[s]) z[s,k],   z ~ Student-t(nu[k])

- **E: energy-cost pass-through.** Brent (x) and the region's gas price (g), lags 0–12, or 0–2
  for motor fuel and air fares.
- **D: supply-disruption months.** 2022-03 to 2022-12 (Russia's invasion and the embargoes) and
  2026-03 onwards (the Hormuz closure).
  - **kappa** is the extra share of energy-cost pass-through in those months. It is pooled across
    the three regions for each kind of item, because each event is short.
  - **psi** widens the band in those months.
  - A fit that ends before 2026 has only 2022 to learn from. That is the point of the 2026 test.
- **v: recent oil volatility** (log mean |x| over 3 months), so the band widens when oil is
  turbulent. This is the volatility-state term that carried the Brent model.
- **season:** month-of-year terms, for the series that are not seasonally adjusted (UK, euro area).
- **rho:** each series' momentum.
- **Noise in forecasts:** a bootstrap of the fitted standardised residual vectors, one whole month
  at a time. The items keep their cross-correlation, so the composite's band is not artificially
  narrow.

**Benchmarks:**
- **Average link:** OLS on the same oil and gas lags with month terms and normal errors, fitted on
  the same months. It is the standard approach and the one the app uses today.
- **Climatology:** the training mean and spread of h-month changes.

## Brent and gas paths: the Lévy model

- **Daily GARCH-CGMY (Lévy).** Forecasts and scenarios take Brent from the daily GARCH-CGMY model
  of `levy_fourier.py`, the best-scoring family on daily Brent.
  - They use the yearly refits already stored from Iridis (`runs/levy/rolling-YYYY.json`), each
    trained only on the days before 1 January of that year. So an origin never sees its own
    future.
  - Daily paths start from the origin's GARCH volatility and are averaged into calendar months
    (21 trading days), to match the monthly-average Brent the items are fitted on.
- **Competitors.** A daily GARCH-Student-t (same stored fits) and a monthly GARCH-t (refitted at
  each origin) are scored against it, on Brent itself and on the items.
- **Closure scenarios.** These add the 2026 closure's monthly Brent and gas moves, scaled by
  severity (25%, 50%, as in 2026). The move enters as a level step on the first day of each month.
  It shifts the path but is not counted as a GARCH surprise, so it doesn't inflate the band by
  construction; the band widens through the supply-disruption terms instead.
- **Gas** = beta × Brent's monthly change + its own monthly GARCH-t residual.

## How it is tested

| Test | What it answers |
|---|---|
| Event misses (no model fit) | How far the average link, fitted up to the month before, fell short in 2022 and 2026, item by item, given the oil and gas that happened |
| 8 forward-chaining folds, 2008–2025 (216 origins) | Skill and 90% coverage at 1, 3, 6 and 12 months: the Bayesian model given oil and gas, the same without supply-shock terms, the average link, and forecasts with each Brent model |
| Feature tests (Newey–West errors) | Bayesian vs average link; supply-shock terms on vs off; Lévy vs Student-t vs monthly Brent paths; composite vs direct headline |
| 2026 event test | Fitted to Feb 2026 with kappa learned from 2022 only: do the bands cover what happened by Sep 2026? |
| 2022 event test | Fitted to Feb 2022 with no supply-disruption months at all |
| Scenario fans | From Feb 2026: no closure against 25%, 50% and a full 2026-sized closure. How far the band shifts and widens |
| Sampler health | Fits with R-hat above 1.05 or ESS below 100 are left out of every table |

## Status (2026-10-24)

- **Done:**
  - Data for 41 series, the weights, and the event analysis.
  - The model, the report and the Iridis scripts.
  - 9 tests (all passing).
- **First full run (Iridis job 1972141): discarded.**
  - The fits that contain supply-disruption months did not converge: the 2026 test fit had R-hat
    2.2, the all-data fit 2.5, with effective sample sizes near 1. The early folds had R-hat
    1.05–1.14 but were still below the ESS bar.
  - The cause was a bug, not the sampler. The Henry Hub driver and the US household-gas item
    shared the key `us_gas`, so the item overwrote the driver. Every US series was then fitted on
    the CPI gas index as its "gas price", and the gas item on its own current change. That makes
    the posterior degenerate.
  - Fixed: the driver key is now `henry_hub`, and a test checks that keys never clash.
  - Rerun as Iridis job 1972228. Its fits are reported only if they clear the convergence bar.
- **Already clear from the data (no model fit needed):** see the event tables in
  `notes/cost-of-living.md`. In February–September 2026, against the average link given the
  actual oil and gas:
  - Motor fuel rose +31% (US), +27% (UK) and +25% (euro area) against +19%, +12% and +13%
    predicted.
  - Air fares +21% (UK) against +13%.
  - Household gas +12% (UK) against about −1%.
  - Food (bread, meat, dairy) was flat or slightly down against +0.7% to +2.0% predicted.
  - Headline came out close to the link in the US (+2.7% against +2.5%) only because those errors
    offset. The UK and euro area were under-predicted by about 1 pp.

## Running it

```bash
uv run experiments/cost_of_living.py events            # event misses and fuel ratios (no MCMC)
uv run experiments/cost_of_living.py fit fold-3        # one fit; names: fold-0..7, event-2022, event-2026, final
uv run experiments/cost_of_living.py check event-2026  # tiny sampler, to smoke-test the pipeline
uv run experiments/cost_of_living.py report            # notes/cost-of-living.md and the two CSVs
```

On Iridis, copy up `experiments/`, `cluster/`, `data/raw/` and `runs/levy/rolling-*.json`, then:

```bash
bash cluster/iridis/cost_of_living_env.sh
sbatch --array=0-10 cluster/iridis/cost_of_living.slurm
```

## Outputs for the UI

- `notes/cost-of-living-fans.csv`: one row per origin × scenario × series × months ahead.
  - Columns: `origin, scenario, series, region, kind, months_ahead, q05, q25, q50, q75, q95,
    actual, weight, generated`.
  - Scenarios: `none`, `closure_25`, `closure_50`, `closure_100`, `whatif` (from Feb 2026) and
    `outlook` (from the latest month).
  - Values are the % change in the price level since the origin.
- `notes/cost-of-living-responses.csv`: each series' response to a sustained +10% Brent move,
  1–12 months on, in normal and supply-disruption months.
  - Includes its weighted contribution to the region's composite (percentage points of headline).

## Limits

- **Two supply events since 2000**, and they differ. kappa is learned from very little, which is
  why it is pooled across regions and has to earn its place on the 2026 test.
- **Fixed weights.** The composite uses the latest weights for every year. That is exact in the
  data by construction, but in forecasts it ignores how the basket shifted.
- **Category mismatches:**
  - US meat includes fish and eggs.
  - US fruit and vegetables is one index.
  - Euro-area weights are for the current euro area, while the indices are the 19-country series.
- **Yearly Lévy fits.** An origin in October uses a fit that ends the previous December.
- **No fertiliser or grain driver.** Food is driven by oil and gas only. 2022's food surge (grain,
  fertiliser) is outside what the model can explain, and it shows in the event table.
