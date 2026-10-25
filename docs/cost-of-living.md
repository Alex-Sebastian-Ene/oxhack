# Cost of living by basket item

Technical notes for the cost-of-living layer of the knock-on chain in [design.md](design.md). It
builds on the links in [knock-on-validation.md](knock-on-validation.md), the Bayesian pass-through
in [macro-ensemble.md](macro-ensemble.md) and the Brent model in [oil-price-model.md](oil-price-model.md).

| Code | What it does | Output |
|---|---|---|
| `experiments/cost_of_living.py` | Basket data and weights, the event misses, the Bayesian item model, Brent and gas paths, folds, event tests, scenario fans | `runs/col/*.json` (git-ignored) |
| `experiments/cost_of_living_report.py` | Tables from the runs; leaves out any fit whose chains did not converge; the disruption multiplier for every metric; compares the other versions | `notes/cost-of-living.md`, `notes/cost-of-living-fans.csv`, `notes/cost-of-living-responses.csv`, `notes/cost-of-living-contributions.csv`, `notes/cost-of-living-multipliers.csv` |
| `cluster/iridis/cost_of_living{_env.sh,.slurm}` | Iridis environment and the 33-task array (11 fits for each of three versions) | |
| `tests/test_cost_of_living.py` | Rest of basket, average link, simulation terms, driver contributions, CRPS, Brent paths, the World Bank file | |

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

Fourteen kinds of item in each region, plus the rest of the basket and headline (51 basket
series; with the chain's other metrics, which sit outside the basket, 70 in all). The items don't
overlap, so their weights add up.

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
| **Housing** | `CUSR0000SEHA` rent and `CUSR0000SEHC` owners' equivalent rent | D7CE actual rents | CP041 actual rentals (`CP0410EZ19M086NEST`) |
| **Core goods** | `CUSR0000SACL1E` (commodities less food and energy commodities) | DK9J (non-energy industrial goods) | `IGD_NNRG` (non-energy industrial goods, `prc_hicp_minr`, EA19) |
| **Other services** | services less energy services (`CUSR0000SASLE`) less rent, OER and air fares | services (D7F5) less rents, air fares and restaurants | services (`SERV`, `prc_hicp_minr`, EA19) less rentals, air fares and restaurants |
| Headline | `CPIAUCSL` | D7BT | CP0000 |

- **Housing** is rent plus, in the US, owners' equivalent rent. UK CPI and the euro-area HICP leave
  out owner-occupiers' housing costs: the UK counts them in CPIH, and the HICP not at all. So their
  housing is actual rents only, and the UK and euro-area series aren't comparable with the US one.
- **Other services** are derived like the rest of the basket: (services weight × services −
  Σ weight × service item) / (services weight − Σ item weights). Nothing is counted twice. They
  include medical care, transport services, recreation, education, communication, insurance,
  personal services and, in the US, lodging away from home.
- **Euro-area services and core goods** come from Eurostat's COICOP 2018 dataset `prc_hicp_minr`
  (EA19, 2015 = 100), the only source with them through 2026: the older `prc_hicp_midx` and the
  ECB's copies stop at 2025-12, and FRED doesn't carry them.
- **Weights:**
  - US: BLS relative importance, CPI-U, December 2025. BLS blocks scripted downloads, so these
    were read from the published table (2026-10-24, and 2026-10-25 for rent 7.840, OER 26.204,
    core goods 19.176 and services less energy services 60.744) and are in the code with that source.
  - UK: ONS CPI weights (CJWB … CJYL; CJVC rents, A9ER non-energy industrial goods, ICVI services), 2026.
  - Euro area: Eurostat `prc_hicp_inw`, 2025.

  | Share of the basket | US | UK | Euro area |
  |---|---|---|---|
  | The original 11 or 12 items | 18% | 26% | 30% |
  | Housing | 34.0% | 8.4% | 5.9% |
  | Core goods | 19.2% | 27.7% | 25.6% |
  | Other services | 25.8% | 32.2% | 30.5% |
  | Rest of the basket | 2.9% | 5.9% | 7.6% |
- **Rest of the basket** = (headline − Σ weight × item − weight × other services) / rest weight,
  each month. The composite (weighted items + other services + rest) therefore equals headline
  exactly in the data. It can only differ from a direct headline model in its forecasts, which is
  what the tests check. With the split it is small: other food (beverages, other food at home),
  alcohol and tobacco outside the US, and other fuels. It also absorbs the aggregation residual,
  because seasonally adjusted indices and fixed latest weights don't add up exactly over 25 years.
  So the US rest swings about 3.5% a month on a 2.9% weight: read it as a remainder, not a price.
- **Drivers:**
  - Brent: monthly average of the daily FRED `DCOILBRENTEU` series.
  - Gas: Henry Hub, monthly (`MHHNGSP`), for the US; the IMF EU gas price (`PNGASEUUSDM`) for the
    UK and euro area.
  - Grain prices: the mean of IMF wheat (`PWHEAMTUSDM`) and maize (`PMAIZMTUSDM`) via FRED, for
    bread and cereals in the main model.
  - Urea, from the World Bank Pink Sheet (updated 2 October 2026), in the rejected grain-and-urea
    version only.

**The chain's other metrics** are fitted in the same model so each gets its own disruption
multiplier. They are not part of any composite (19 series, 60 in all):

| Kind | Series |
|---|---|
| Industry fuel (US) | Retail diesel (`GASDESW`), Gulf Coast jet fuel (`DJFUELUSGULF`), refinery PPI; lags 0–2 |
| Freight and air transport (US) | PPIs for long-distance truckload and trucking, deep-sea freight, air freight and passenger air; lags 0–2 |
| Materials (US) | PPIs for plastics resin, film and bags, bottles, converted paper and paperboard, nitrogen fertiliser; lags 0–12 |
| Unemployment | US (`UNRATE`), UK (OECD via FRED), euro area (Eurostat EA21); changes in pp |
| Policy rate | Fed funds, SONIA, ECB deposit rate; changes in pp, with a wider error floor because rates move in steps |

## Model

One Bayesian model for all 70 series, on monthly log changes (% of the price level; changes in
percentage points for unemployment and rates), fitted by
NUTS (2 chains, 500 warm-up, 1,000 draws per chain):

    y[s,k] = a[k] + season[k, month] + rho[k] y[s-1,k] + E[s,k] (1 + kappa[k] D[s]) + F[s,k] + e[s,k]
    E[s,k] = sum_l B[k,l] x[s-l] + sum_l G[k,l] g_r(k)[s-l]
    F[s,k] = sum_l C[k,l] grain[s-l]   (bread and cereals only; 0 for every other series)
    e[s,k] = sigma[k] exp(phi[k] v[s] + psi[k] D[s]) z[s,k],   z ~ Student-t(nu[k])

- **E: energy-cost pass-through.** Brent (x) and the region's gas price (g), lags 0–12, or 0–2
  for motor fuel and air fares.
- **F: grain prices for bread and cereals** (the mean monthly log change of IMF wheat and maize),
  lags 0–12, in all three regions. It was added after the comparison below, and is the only food
  input the main model keeps.
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
- **Versions** (`COL_FOOD`), each with its own runs folder and scored on the same folds and seeds:
  - `bread`, the default and main model (`runs/col-food-bread`): grain for bread and cereals.
  - `0`, the base model with oil and gas only (`runs/col`), which the main model replaced.
  - `1`, grain and urea for every food item, restaurants, the rest of the basket and headline
    (`runs/col-food`). Tested and rejected.
- **Contributions:** every run also breaks each series' change in the 2022 and 2026 windows into
  the part each driver group's moves explain (oil, gas, and grain or urea where the version has
  them).

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
| Against the Fed and the SPF | US CPI in forecast mode against the Cleveland Fed, Michigan and SPF forecasts and the random walk, from `runs/macro/global-benchmarks.json` (the chain's, same folds, matched by origin month; Diebold–Mariano tests with 12 Newey–West lags) |
| Sampler health | Fits with R-hat above 1.05 or ESS below 100 are left out of every table |

## Status (2026-10-25)

- **Current run: the basket split and the chain's other metrics, fitted together (Iridis job
  1973432, 33 fits).** The basket now has housing, core goods and other services as their own
  series, so 92–97% of each basket is modelled item by item, against 18–30% before. The US industry
  costs, unemployment and policy rates are fitted alongside, outside the composites (70 series in
  all).
  - **Convergence:**
    - Every fit of the main model: R-hat 1.011–1.023, ESS 103–411, no divergences.
    - Every fit of the oil-and-gas base: R-hat 1.008–1.024, ESS 171–408.
    - Folds 0 and 2 of the grain-and-urea variant, the one that was already rejected, fell short
      at first (R-hat 1.17 with ESS 7; ESS 92). Refitted with 1,500 warm-up and 2,000 draws (job
      1973701), both converged (R-hat 1.016 and 1.009, ESS 218 and 419), so every fit is in the
      report.
  - `notes/cost-of-living.md` and the four CSVs come from this run. The numbers below are from the
    main model, given the oil and gas that happened, over the 8 folds (2008–2025), unless marked.
- **Housing, core goods and other services:**
  - **Skill against climatology:**

    | | Main model | Average link (OLS) | Forecast, Lévy Brent paths | 90% coverage |
    |---|---|---|---|---|
    | Housing | +0.085 | −0.169 | +0.123 | 74% |
    | Core goods | +0.145 | +0.098 | +0.156 | 80% |
    | Other services | +0.099 | +0.048 | +0.100 | 71% |

    Their bands are too narrow, most for other services and housing. Those prices drift slowly, and
    one month's momentum doesn't see shifts like the 2021–23 rent surge.
  - **The composites improve or hold.** Composite skill before → after the split: US +0.355 →
    **+0.394**, UK +0.211 → +0.214, euro area +0.329 → +0.338. Coverage: US 83% → 85%, UK
    78% → 77%, euro area 74% → 76%.
  - **Disruption multipliers below 1:** housing ×0.42–0.51, core goods ×0.25–0.28, other services
    ×−0.14 to −0.22. Energy costs pass through to these more weakly in supply-disruption months,
    not more strongly.
  - **2026 test (fitted to Feb 2026, 7 months on):** of the basket's 54 outcomes, all but one are
    inside the bands. The miss is euro-area rents: +1.5% against a band of +0.8 to +1.4.
  - **Scenario from Feb 2026, 12 months on:**
    - A 2026-sized closure barely moves rents or other services: US rent +2.7% with no closure,
      +3.0% with one.
    - It widens the core-goods band, from 5.3 to 9.4 pp in the US.
  - **Outlook from 2026-09, 12 months, disruption continuing:**

    | | US | UK | Euro area |
    |---|---|---|---|
    | Rent | +3.4% (0.8 to 6.1) | +2.8% (0.6 to 5.5) | +1.9% (1.1 to 2.6) |
    | Owners' equivalent rent | +3.4% (0.7 to 5.8) | | |
    | Core goods | +0.8% (−2.0 to 4.4) | +0.9% (−1.9 to 3.3) | +1.1% (−2.7 to 4.5) |
    | Other services | +2.8% (1.5 to 4.5) | +3.6% (1.8 to 5.7) | +2.1% (0.2 to 3.9) |
    | Composite | +3.4% (0.6 to 6.6) | +3.9% (1.6 to 6.6) | +3.1% (0.5 to 6.5) |
  - **The remainder is a residual, not a price.** The rest of the basket (3–8%) carries the
    aggregation residual: the latest weights are fixed, while fuel's share of the basket was larger
    in earlier years. So it moves with oil out of proportion to its weight: +36% under a 2026-sized
    closure in the US. Its weighted part is the same residual the old 82% rest held, now visible
    rather than diluted. Read the composites, not the remainder.
- **Done:**
  - Data for 70 series (the basket, split into housing, core goods and other services, and the
    chain's other metrics), the weights, and the event analysis.
  - The model, the report and the Iridis scripts.
  - 14 tests (all passing in all three versions).
- **Main model (adopted 2026-10-25): oil and gas for every series, plus grain prices for bread
  and cereals,** with the chain's other metrics fitted alongside. Out of sample:
  - **Against the average link:**
    - Basket items: better at every horizon, −0.18 ± 0.02 at 1 month to −0.09 ± 0.01 at 12.
    - US industry costs: better, −0.09 ± 0.02 to −0.06 ± 0.02.
    - Unemployment and rates: much better, −0.37 ± 0.03 to −0.28 ± 0.09, mostly through momentum.
  - **Composite against direct headline:**
    - US: better at every horizon (−0.12 ± 0.02, −0.15 ± 0.03, −0.11 ± 0.03, −0.07 ± 0.03). Before
      the split it was better only up to 6 months.
    - Euro area: −0.03 ± 0.02 at 1–6 months, about 2 errors.
    - UK: no difference.
  - **Against the Fed and the SPF (US CPI, forecast mode, nothing known after the origin):** the
    composite's CRPS is lower than every institutional forecast up to 6 months, and level with the
    SPF at 12.
    - 1 month: 27% below the Cleveland Fed (t −5.0), 25% below Michigan (t −5.0) and 31% below the
      SPF median at its release months (t −5.1).
    - 3 months: 16% below Cleveland (t −3.7) and 16% below the SPF (t −3.6); Michigan 12% (t −1.9).
    - 6 months: 13% below Cleveland (t −2.8) and 9% below the SPF (t −3.1); Michigan 10% (t −1.1).
    - 12 months: level with the SPF (2% below, t −0.4); Cleveland and Michigan 11% and 15% worse,
      both within noise (t −1.8, −1.2).
    - **Splitting the rest of the basket moved the composite ahead.** With the old 82% rest it was
      5% below the SPF at 6 months (t −1.4, not significant) and 2% behind at 12.
    - The direct headline forecast does less well: 16–18% below the institutions at 1 month, 3–4%
      behind the SPF at 12. So building the forecast up from the basket is what earns the lead. The
      chain's best member is 2–4% behind the SPF at 12 months (`docs/macro-ensemble.md`).
    - Short horizons favour us: Cleveland and Michigan are 1-year rates scaled down, and the SPF is
      quarterly. The surveys used data as first published; we score on revised CPI. Our 90% bands
      hold 82–88% of outcomes. US only: no UK or euro-area institutional forecasts are scored yet.
  - **Brent paths: Lévy is best at 3–12 months.**
    - Against daily Student-t paths: −0.80 ± 0.51 at 12 months.
    - Against a monthly GARCH-t: −1.98 ± 1.08 at 12 months.
    - At 1 month it is level with Student-t and well ahead of the monthly model (CRPS 3.98 against
      5.29).
  - **About the 2026 test:** it is a what-if. It is given the oil and gas that happened, and it is
    told the months from 2026-03 are a disruption (D = 1, from the calendar). So it shows what the
    model gets right given the scenario, not what it would have foreseen. The forecast mode only
    carries D forward from the origin, and the scenario fans switch D on from the closure severity.
  - **2026 test (fitted to Feb 2026), basket:**
    - The bands hold 53 of 54 outcomes, against 46 without the supply-shock terms and 44 for the
      average link.
    - The mean miss of the median is 2.5 pp, against 2.8 and 2.8.
    - Motor fuel: UK +24.1% predicted against +27.4% actual; euro area +27.7% against +25.4%; US
      +36.6% against +30.8%.
  - **2026 test, industry costs, unemployment and rates:** 15 of 17 outcomes inside the bands,
    against 9 of 17 both without the terms and for the average link. The mean miss of the median is
    7.9 pp, against 9.4 and 10.0.
    - Diesel: +52.5% actual, against +28.2% predicted (band −6 to +65) and +14.3% from the link.
    - Jet fuel: +66.2%, against +44.4% (band −17 to +95) and +38.2%.
    - Refineries: +62.9%, against +42.0% (band 4 to 82) and +33.1%.
    - The link's bands miss all three.
  - **2022 test: still missed.** 19 of 54 basket outcomes inside the bands (13 for the average
    link), with misses of about 11 pp.
  - **Calibration:** 71–94% of basket outcomes inside the 90% bands, against 54–86% for the
    average link.
  - **Scenario from Feb 2026, 12 months on.** A 2026-sized closure lifts cost-of-living inflation:
    - US: from +2.4% to +5.2%.
    - UK: from +2.6% to +4.9%.
    - Euro area: from +2.0% to +5.3%.
    - It widens the 90% band from 3.2–3.9 pp to 5.0–7.3 pp.
- **The disruption multiplier for every metric** (1 + kappa, all-data fit; the full table is in
  `notes/cost-of-living.md` and `notes/cost-of-living-multipliers.csv`):
  - **Clearly above 1:**
    - Headline inflation ×1.51 (US), ×1.50 (UK), ×1.58 (euro area); each interval's lower end is
      just above 1.
    - Motor fuel ×1.49–1.55.
    - Dairy ×1.9.
    - US retail diesel ×1.31 (1.02 to 1.72).
  - **Clearly below 1:**
    - Oils and fats (about ×0) and fruit and vegetables (×0.3–0.5): their pass-through all but
      vanished in the disruption months.
    - Housing, core goods and other services (above).
  - **Within noise:**
    - Jet fuel ×1.20, refineries ×1.19.
    - Freight and air ×1.5 (wide).
    - Materials and fertiliser ×1.0–1.1.
    - Household energy, restaurants, the rest of the basket.
    - Policy rates ×1.4, on effects of about 0.03 pp.
  - **Cost of living (composites):** ×1.20 (US), ×0.91 (UK), ×1.25 (euro area), as the ratio of
    the 12-month responses in disruption and normal months. They are lower than before the split
    (×1.19, ×1.17, ×1.29) where housing and services carry more weight, as they do in the UK basket.
  - **Unemployment ×−0.22 to −0.28 (US −0.60 to 0.19):** the usual oil-up, unemployment-down
    comovement disappears in supply shocks. The effect is about 0.0 pp either way, so it isn't a
    link to show.
  - **One multiplier for everything would be wrong.** Use each metric's own: ×1.5 suits motor fuel
    and headline inflation, but it would overstate the composites, freight and materials, and get
    oils, fruit and vegetables, housing and services the wrong way round.
- **History:** the runs below led to the main model.
- **First full run (Iridis job 1972141): discarded.**
  - The fits that contain supply-disruption months did not converge: the 2026 test fit had R-hat
    2.2, the all-data fit 2.5, with effective sample sizes near 1. The early folds had R-hat
    1.05–1.14 but were still below the ESS bar.
  - The cause was a bug, not the sampler. The Henry Hub driver and the US household-gas item
    shared the key `us_gas`, so the item overwrote the driver. Every US series was then fitted on
    the CPI gas index as its "gas price", and the gas item on its own current change. That makes
    the posterior degenerate.
  - Fixed: the driver key is now `henry_hub`, and a test checks that keys never clash.
- **Base model rerun (Iridis job 1972228): all 11 fits converged.** It was then refitted at 1,000
  draws per chain (job 1972574). This base model, with oil and gas only, is what the main model
  replaced; the verdicts below are its own.
  - Convergence: R-hat 1.006–1.021, ESS 200–581, no divergences.
  - Iridis reproduced the laptop's fold-1 refit to every digit (same seed and draws).
  - Verdicts:
  - **Bayesian item model against the average link: keep.** It is better at every horizon: −0.18 ±
    0.02 at 1 month to −0.07 ± 0.01 at 12, in units of climatology CRPS.
  - **Lévy Brent paths: keep.**
    - On Brent itself they score best at every horizon.
    - Against daily Student-t paths: −0.70 ± 0.51 at 12 months, not significant.
    - Against a monthly GARCH-t: −2.01 ± 1.11, and clearly better at 1 month (CRPS 4.00 against
      5.24).
    - On the items they tie with Student-t, and beat the monthly model at 1 month (−0.006 ± 0.002).
  - **Composite against direct headline: keep, region by region.**
    - US: better up to 6 months (−0.09 ± 0.02 at 1 and 3 months, −0.06 ± 0.03 at 6).
    - Euro area: slightly better at 1 month (−0.02 ± 0.01, just under 2 errors).
    - UK: no difference.
  - **Supply-shock terms: keep, on the 2026 test.**
    - The folds can't judge them, because their only supply months are in 2022.
    - Fitted to Feb 2026 with kappa learned from 2022 alone, the bands cover 44 of 44 outcomes by
      Sep 2026. That compares with 37 of 44 without the terms and 37 of 44 for the average link.
      The median miss is 2.6 pp, against 3.2 and 3.2.
    - Motor fuel: UK +24.5% predicted against +27.4% actual (+10.9% without the terms); euro area
      +28.0% against +25.4% (+13.7%); US +34.4% against +30.8% (+19.4%).
    - The cost is wide bands on some items.
  - **2022: nothing predicts it.** At best 17 of 44 outcomes are inside the bands, with misses of
    about 11 pp. It was a gas and grain shock outside the model's drivers.
  - **Calibration is still short of 90%** for several groups out of sample (restaurants 73%,
    euro-area headline 73–74%). That is better than the average link (62–86%), but the bands need
    recalibrating.
  - **Scenario from Feb 2026.** A 2026-sized closure lifts 12-month cost-of-living inflation:
    - US: from +2.4% to +4.7%.
    - UK: from +2.5% to +4.1%.
    - Euro area: from +2.0% to +4.4%.
    - It also roughly doubles the width of the 90% band: US 4.0 → 8.0 pp, UK 3.3 → 6.4, euro
      area 3.1 → 7.0.
- **Food drivers (job 1972574): tested, not kept.** Grain prices (wheat and maize) and urea were
  added as 0–12-month drivers of the food series.
  - **Out of sample they make food forecasts worse at every horizon.**
    - Given the drivers: +0.10 ± 0.01 at 1 month to +0.10 ± 0.04 at 12.
    - As forecasts: +0.10 ± 0.01 at 1 month to +0.05 ± 0.02 at 12.
    - Fruit and vegetables, meat and dairy lose the most. UK headline is worse at 1–3 months.
  - **They don't fix 2022.** 7 of 26 food series and composites fall inside the bands, against 8
    of 26 without them.
  - **They barely change 2026.** 26 of 26 both ways; median miss 1.6 against 1.8 pp.
  - **Why: their own moves in the windows explain little.** From February to December 2022 they
    added at most about 2 pp to any food item, against actual rises of 6–28%. The 2022 food surge
    came through channels outside the drivers: energy and labour in processing and retail,
    margins, and moves slower than the 12-month lags.
  - **What they do tell us** (all-data fit, per sustained +10% move, 12 months on):
    - Grain prices lift bread by +0.6% in the US (0.5 to 0.8) and the UK (0.2 to 1.1), and by
      +0.3% in the euro area. They lift UK oils and fats by +1.3%.
    - Urea lifts US meat by +0.3% and US fats and oils by +0.5%.
    - Read these as information, not as a model to forecast with.
  - Fold 0 of the food version first reached ESS 39. It was refitted with 1,000 warm-up and 2,000
    draws (R-hat 1.02, ESS 183).
- **Targeted food driver (job 1972769): grain prices for bread and cereals only, all three
  regions.** The rule was fixed on economic grounds before the run, not chosen from the item
  results above. All 11 fits converged (R-hat at most 1.03, ESS at least 165). A rerun of base
  fold 0 matched the earlier one exactly.
  - **US bread and cereals: clearly better at 3–12 months,** beyond 2 errors, both given the
    drivers (−0.09 ± 0.03 at 3 months to −0.16 ± 0.07 at 12) and as true forecasts (−0.12 ± 0.03 to
    −0.19 ± 0.06). Its skill rises from 0.08 to 0.21–0.23.
  - **UK and euro-area bread: slightly worse, within noise** (up to +0.04 ± 0.03).
  - **Pooled over the three regions:** bread skill rises from 0.144 to 0.173 (0.146 to 0.184 as
    forecasts). The gain at 3–12 months stays within its errors.
  - **Composites and every other food item: unchanged,** with differences of 0.007 or less.
  - **2022 is still missed:** US bread +3.7% predicted against +13.6% actual.
  - **In 2026 the US bread median moves closer:** +1.1% against +2.6% before, with +0.5% actual.
  - **Grain → bread** (all data, per sustained +10% grain move, 12 months on): US +0.69% (0.51 to
    0.86), UK +0.66% (0.25 to 1.03), euro area +0.32% (0.14 to 0.51).
  - **Verdict:** unlike the full version it never does worse beyond noise, and it clearly improves
    US bread. The evidence is strongest in the US. Adopted as the main model on 2026-10-25.
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
uv run experiments/cost_of_living.py fit fold-3        # one fit of the main model; names: fold-0..7, event-2022, event-2026, final
uv run experiments/cost_of_living.py check event-2026  # tiny sampler, to smoke-test the pipeline
uv run experiments/cost_of_living.py report            # notes/cost-of-living.md and the CSVs
COL_FOOD=0 uv run experiments/cost_of_living.py fit fold-3  # the oil-and-gas-only base
COL_FOOD=1 uv run experiments/cost_of_living.py fit fold-3  # grain and urea for every food item (rejected)
uv run experiments/macro_global.py benchmarks          # Fed and SPF forecasts for the report (skipped if absent)
```

Fit on Iridis rather than the laptop: a fold takes about a minute there. Copy up `experiments/`,
`cluster/`, `data/raw/` and `runs/levy/rolling-*.json`, then:

```bash
bash cluster/iridis/cost_of_living_env.sh
sbatch --array=0-21 cluster/iridis/cost_of_living.slurm
```

Tasks 0–10 are the base model, 11–21 the food-driver version (`COL_FOOD=1`) and 22–32 the main,
bread-only version (`COL_FOOD=bread`). All use 1,000 draws per chain (`COL_SAMPLES`).

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
- `notes/cost-of-living-contributions.csv`: in the 2022 and 2026 windows, the part of each series'
  change that each driver's moves explain (oil, gas, and grain for bread), month by month, next to
  the actual.
  - Columns: `base_month, months_after, series, region, kind, driver, contribution_pp, actual_pp,
    generated`.
- `notes/cost-of-living-multipliers.csv`: every metric's supply-disruption multiplier (1 + kappa,
  median and 90% interval), with its 12-month response to +10% Brent in normal and disruption
  months.
  - Columns: `series, region, kind, multiplier_q50, multiplier_q05, multiplier_q95,
    response_normal_12m, response_disruption_12m, unit, fitted_to, generated`.
  - The composites' multiplier is the ratio of those two responses.
- All four CSVs come from the main model.

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
- **Unemployment and rates have no validated oil link.** Their multipliers scale effects of a few
  hundredths of a point, so the app should keep showing 0 or a labelled range.
- **Industry costs are US only.** Their multipliers are pooled within each group (fuel, transport,
  materials) rather than across regions.
- **Food is driven by oil, gas and, for bread, grain.**
  - Grain and urea for every food item made forecasts worse, so they stay out.
  - Grain for bread alone helps US bread and harms nothing beyond noise, so the main model has it.
  - 2022's food surge is outside what the model can explain, and it shows in the event table.
  - A leaner food term might do better: one 12-month grain change per item, or vegetable oils for
    oils and fats. That is untested.
