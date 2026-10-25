# Knock-on ensemble: regions, industry, oil, AIS and pipelines

Technical notes for the multi-region version of the knock-on chain in [design.md](design.md). It
extends the single-country links in [knock-on-validation.md](knock-on-validation.md) and the
oil-price layer in [oil-price-model.md](oil-price-model.md).

| Code | What it does | Output |
|---|---|---|
| `experiments/macro_data.py` | Fetches and aligns every input (monthly, 2000 on) with publication lags | `notes/macro-panel.md` |
| `experiments/macro_nn.py` | Deep ensemble, baselines, stacker, folds, diagnostics, oil-shock responses | `notes/macro-nn-results.md` |
| `experiments/macro_bayes.py` | Bayesian pass-through fitted by MCMC: pooled oil lags, momentum, asymmetry, volatility-driven bands (oil, own, drifting); what-if and genuine forecasts; benchmarks | `notes/macro-bayes-results.md`, `notes/macro-bayes-responses.csv` |
| `experiments/macro_global.py` | One network shared by the 22 targets, one month ahead (own lags, oil lags, series embedding, Student-t head), simulated like the Bayesian model; least-squares benchmark on the same inputs | `notes/macro-global-results.md` |
| `experiments/sector_global.py` | The global network on industries by country (`--set sectors`: producer prices and output of 20 mining, refining and metals industries in 35 European countries and the US, 9 world mineral prices), on specific goods (`--set goods`: 30 European goods by country, 46 US goods, 15 household goods in 37 countries, ~50 world prices) and on prices in ~170 nations (`--set nations`: headline, energy, food and producer prices) | `notes/sector-global-results.md`, `notes/goods-global-results.md`, `notes/nations-global-results.md` |
| `experiments/flow_price.py` | Hormuz flow (AIS) → Brent: regression and 2026 closure event study | `notes/flow-price-link.md` |
| `experiments/hdi_link.py` | Oil prices against UNDP Human Development Index (annual) | `notes/hdi-link.md` |
| `cluster/iridis/macro_*.{sh,slurm}` | Iridis environment, 9-task main array, diagnostics array | |

## Inputs (blocks)

Each series is registered once, with its source, transform, publication lag (months between the
month it describes and its release) and role. Blocks switch on by name, so a region or source is
added by adding rows. The full table, with date ranges and fetch dates, is in
`notes/macro-panel.md`.

| Block | Series | Sources |
|---|---|---|
| `oil` | Brent, WTI, Kilian global real activity, geopolitical risk index | FRED, Caldara & Iacoviello |
| `ais` | Tanker transits and capacity through Hormuz, Bab el-Mandeb, Cape of Good Hope (share of 2019–24 normal) | IMF PortWatch (from AIS, 2019 on) |
| `pipeline` | Tanker exports at the pipelines' sea ends (Yanbu for the East-West pipeline, Fujairah for Habshan–Fujairah) against exports from ports inside the Gulf | IMF PortWatch daily ports |
| `fuel` | US crude stocks, SPR, refinery utilisation, gasoline and distillate demand, crude imports and production | EIA weekly history files |
| `drivers` | Supply-chain pressure, food prices, US and EU gas, 1-year inflation expectations, M2, import prices, shelter CPI, wages | NY Fed, IMF, EIA, Michigan, Fed, BLS |
| `us` | CPI, core CPI, unemployment, fed funds, 10y, industrial production, payrolls, sentiment, PPI, productivity | FRED (BLS, Fed) |
| `uk` | CPI (ONS D7BT), unemployment, SONIA (stands in for Bank Rate), 10y, production, productivity, GBP/USD | ONS, FRED |
| `ea` | HICP, unemployment (EA21), ECB deposit rate, industrial production, EUR/USD | Eurostat, FRED |
| `industry` | Diesel, jet fuel, freight PPIs (trucking, deep-sea, air), materials PPIs (plastics, paperboard, fertiliser), refineries, air fares | FRED, read from Eileen's `notes/industry/fred_series.csv` |
| `sectors` (sector runs only) | Producer prices and output of 20 industries (mining, oil refining, chemicals, cement, basic metals, metal refining, aluminium, copper, …) in every European country that publishes them, and the closest US industries | Eurostat `sts_inppd_m`, `sts_inpr_m`; FRED (BLS PPIs, Fed industrial production) |
| `commodities` (sector runs only) | World prices of copper, aluminium, nickel, zinc, lead, tin, iron ore, coal, uranium | IMF via FRED |
| `goods` (goods runs only) | Producer prices and output of 30 specific goods (finest NACE classes: plastics in primary forms, fertilisers, cement, flat glass, paper, sugar, flour, …) by European country; producer prices of 46 US goods (diesel, jet fuel, asphalt, resins, steel mill products, copper wire, cement, …) | Eurostat `sts_inppd_m`, `sts_inpr_m`; FRED (BLS commodity PPIs) |
| `household` (goods runs only) | Consumer prices of 15 household goods (motor fuels, diesel, petrol, heating oil, gas, electricity, bread, meat, dairy, oils, sugar, rail and air fares) in 37 countries | Eurostat `prc_hicp_minr` (HICP, COICOP 2018) |
| `world` (goods runs only) | About 50 world prices: fertilisers (urea, DAP, potash), grains, vegetable oils, sugar, coffee, rubber, timber, metals, coal, gas | World Bank Pink Sheet |
| `nations` (nations runs only) | Headline, energy and food consumer prices and producer prices in 168 countries (housing and utilities where there is no energy index) | World Bank Global Database of Inflation |

- **Rules that protect the results:**
  - Only data public at the end of a month enter that month's inputs (the publication lags).
  - Short gaps are filled on the *level*, so a filled month reads as "no change". The missing
    October 2025 US releases are one example.
  - Late-starting blocks (`ais`, `pipeline`) are zero before 2019, with an availability flag.
  - AIS flows are shares of normal, not log changes: Hormuz tanker capacity fell 98% in March
    2026, a log change of about −4.
- **Targets:** inflation, unemployment and the policy rate in each region, plus the 13 industry
  costs, as changes over 1, 3, 6 and 12 months. That's 88 outputs.
- **Conditioning:** the forecasts are conditional on the oil path over the next 12 months, which
  is what the what-if needs.

## Models

| Model | Architecture |
|---|---|
| `tcn` | Dilated causal convolutions (residual blocks, LayerNorm) over a 24-month window |
| `transformer` | Linear projection, learned positions, pre-LN Transformer encoder; last-step and mean pooling |
| `tcn_transformer` | TCN for local patterns, then a Transformer over its outputs |
| `lstm` | 1–2 layer LSTM |
| `nbeats` | N-BEATS-style residual MLP blocks on the flattened window (normalised input) |
| `*_skip` | Any of the above plus a linear oil-path term added to the mean, without weight decay |
| `nn_mean` | Equal-weight mixture of every network's deep ensemble |
| `stack` | MLP stacker with an encoder. Per output it encodes the latest month and the output's identity, weighs every model's forecast (softmax) and rescales the spread. Trained on held-out validation forecasts |
| `ridge`, `no_change`, `climatology` | Baselines |

- **Outputs:** every network produces a Gaussian (a mean and a log-variance per output) and is
  trained by masked negative log-likelihood (AdamW, early stopping).
- **Sizes and seeds:** each network comes in a base size (64 wide, 2 layers) and a scaled-down
  size (24 wide, 1 layer), each trained with **6 seeds**. The seeds' forecasts are combined as a
  moment-matched mixture, i.e. a deep ensemble.
- **Standardisation:** inputs and targets are standardised with training-fold statistics only.
- **Scoring:** forward-chaining folds, 8 test blocks from 2008 to 2025, with a 12-month gap before
  each so no training target overlaps the test block. The score is CRPS, reported as skill
  against climatology. There are also 90% interval coverage, a learning curve by fold, a
  crisis/calm split, diagnostics, and the response to a +10% Brent move.

## Results with the v1 inputs (oil, AIS, regions, industry)

Iridis job 1971341: 8 folds, 214 test origins (2008-01 to 2025-10). Diagnostics are job 1971356
(7 variants × 8 folds). Skill is 1 − CRPS / CRPS of climatology, over all horizons; 0 means no
better than forecasting the historical average.

| Target group | Best | Skill | Ensemble mean (`nn_mean`) | Stacker | Ridge |
|---|---|---|---|---|---|
| Inflation (3) | LSTM | +0.024 | +0.004 | −0.153 | −0.033 |
| Unemployment (3) | ridge | +0.104 | +0.047 | +0.026 | +0.104 |
| Policy rate (3) | no change | +0.046 | +0.025 | +0.026 | −0.326 |
| Industry costs (13) | LSTM | +0.066 | +0.009 | −0.017 | −0.091 |

### The biggest issues, as the diagnostics show them

1. **Too little data for deep models.** There are 287 monthly origins in all, and only 61 in
   fold 0. The networks beat climatology by a few percent at most, no architecture wins
   consistently, and more data (later folds) doesn't raise the ensemble's skill above about
   0.03. The stacker overfits its small validation set, and it is the worst learned model.
2. **The networks under-react to oil by 6–9×.**
   - A +10% Brent move gives US CPI +0.03 to +0.06 pp after 12 months, against +0.36–0.40 pp for
     the validated linear link.
   - Diesel moves about +1%, against about +6% expected.
   - Flexible models spread the oil effect thin across 52 inputs and 88 outputs.
   - Unfixed, they can't drive the what-if, so v2 tests a linear oil skip path.
3. **The bands are too narrow.** Only 70–76% of inflation and unemployment outcomes fall inside
   the nominal 90% interval (rates are about 89%).
4. **The skill comes from knowing the oil path.** Without it, inflation skill drops from +0.022
   to −0.007 and cost skill from +0.061 to −0.010 (`no_oil_path`). Without a scenario, there is
   essentially no forecasting skill.
5. **AIS as a generic input hurts.** Without it, unemployment improves from +0.032 to +0.058 and
   rates from +0.021 to +0.035. It covers only 2019 on; it is used through the flow → Brent link
   instead (below).

**What holds up:**
- **No leakage:** with shuffled training targets, skill falls to 0 or below.
- **Publication lags barely matter:** pretending data arrive immediately changes skill by at most
  0.006.
- **Window length:** a 12-month window is slightly better than 24 months.

## Results with the v2 inputs (adding fuel flows, pipeline bypass exports and inflation drivers)

Iridis jobs 1971471 (5 variants × 8 folds) and 1971472 (fit on all data). These use the reduced
model set: ridge, small LSTM and TCN-Transformer with and without the oil skip path, 3 seeds each,
and the stacker. The v1 `full` row is the reference.

| Ensemble mean skill | Inflation | Unemployment | Rate | Cost |
|---|---|---|---|---|
| v1 inputs (52) | +0.012 | +0.032 | +0.021 | +0.029 |
| v2, all blocks (74) | +0.003 | +0.045 | −0.000 | +0.012 |
| v2 without `fuel` | +0.010 | +0.041 | +0.005 | +0.013 |
| v2 without `pipeline` | +0.014 | +0.041 | +0.009 | +0.011 |
| v2 without `drivers` | +0.017 | +0.045 | +0.015 | +0.011 |
| v2 without `ais` and `pipeline` | +0.007 | +0.051 | +0.012 | +0.016 |

- **The extra blocks don't help on this data.** Fuel flows, pipeline exports and the other
  inflation drivers add inputs but no forecastable information beyond the oil path. Removing any
  one of them changes skill by about as much as it varies between variants, and ridge collapses
  on unemployment (from +0.104 to +0.001). With 287 monthly origins, more inputs mainly mean more
  ways to overfit.
- **The pipeline block still matters for the story, though.** In a closure, inside-Gulf exports
  collapse while the bypass ports pick up what the pipelines can carry. That belongs in the flow
  estimate (the chain's first link), not in a monthly inflation model.
- **The oil skip path raises the oil response but costs forecast skill.**
  - With the skip, a +10% Brent move gives US CPI +0.20 pp (LSTM) and +0.12 pp (TCN-Transformer)
    after 12 months, against +0.02 and +0.01 without it. Euro-area CPI gives +0.22 and +0.16.
    That is about half of the validated linear +0.36–0.40 pp, up from about a tenth.
  - Industry responses are unstable: diesel is +0.57 for one model and −1.76 for the other.
  - The unpenalised linear path also overfits, so forecast skill falls, most on rates (−0.05 to
    −0.07).
- **Next step:** fix the oil path's coefficients at, or shrink them towards, the validated linear
  pass-through from `oil_chain.py`, and let the networks learn only the residual. That keeps the
  what-if anchored to links that hold out of sample.

The v2 jobs ran the code just before `fold_indices()` was pulled out of `run_fold`. That refactor
changes no indices (`tests/test_macro.py` checks the fold gap).

## The anchored model (oil pass-through fixed to the validated links)

`macro_nn.py fold J --anchored` (Iridis job 1971583, 8 folds plus the final fit; diagnostics job
1971584).
- **The anchor:** each fold fits, on its training months only, the `oil_chain.py` link for every
  target series: its monthly change on Brent lags 0–12 (inflation, unemployment, rates,
  materials) or 0–2 (fuel and freight).
- **Validated links only:** a link is kept only if its summed effect clears 2 Newey–West
  errors. Otherwise the anchor is 0.
- **Residual learning:** every model learns the residual without seeing the oil path, so a
  what-if response is exactly the validated link.
- **Recalibration:** variances are rescaled per output on the validation set, pulled towards
  the series-wide scale.

Skill is measured against the *unanchored* climatology, so both runs share one yardstick.

| | Inflation | Unemployment | Rate | Cost |
|---|---|---|---|---|
| v1, best model | +0.024 (LSTM) | +0.104 (ridge) | +0.046 (no change) | +0.066 (LSTM) |
| v1 ensemble mean | +0.004 | +0.047 | +0.025 | +0.009 |
| Anchored ensemble mean, recalibrated | **+0.147** | −0.137 | −0.144 | **+0.420** |
| Anchored LSTM, recalibrated | **+0.152** | −0.139 | −0.158 | **+0.418** |
| Anchored climatology (anchor + mean residual) | +0.147 | −0.179 | −0.182 | +0.417 |
| **Hybrid ensemble mean** (anchored for prices, v1 for the rest) | **+0.147** | **+0.047** | **+0.025** | **+0.420** |

**Oil-shock responses, now anchored** (+10% Brent next month, change after 12 months, all-data
fit; v1 ensemble mean in brackets):

| Target | Anchored | v1 |
|---|---|---|
| US / UK / euro-area CPI | **+0.43 / +0.34 / +0.35 pp** | +0.03 / +0.02 / +0.03 |
| Diesel / jet fuel / refineries | +5.0 / +9.2 / +8.5% | +0.7 / +0.8 / +0.8 |
| Freight PPIs | +0.6 to +0.8% | +0.1 to +0.2 |
| Plastics, paperboard, fertiliser | +0.7 to +5.8% | +0.0 to +0.7 |
| Unemployment, policy rates | 0 (no validated link in the final fit) | about 0 |

**What it shows:**
1. **Anchoring fixes prices.** Inflation skill rises from about +0.02 to +0.15 and cost skill
   from +0.07 to +0.42. The what-if responses now match the validated links (US CPI +0.43 pp on
   2000–2026 data, against +0.36 for the 1991–2008 fit) instead of a tenth of them.
2. **The gain is the anchor's, not the networks'.** Anchored climatology (the anchor plus each
   series' average drift) scores the same as the networks, which add at most about 0.005. On
   monthly data, the honest price model is the validated linear link plus a drift and a
   calibrated band.
3. **Unemployment and rates get worse when anchored**, for two reasons:
   - The networks lose the oil path, which for these targets stands in for global demand: oil
     collapsed with the 2008 and 2020 unemployment spikes.
   - US unemployment cleared the significance bar in 4 of 8 folds with a *negative* sign (oil
     up, unemployment down). That is demand-driven comovement, not a supply effect, so
     significance alone is not a strong enough validation rule for these targets.

   Hence the hybrid: anchored for inflation and costs, unanchored for unemployment and rates. In
   the what-if, the unanchored targets should stay at 0 or show a range, since they have no
   validated causal link.
4. **Recalibration helps where models were overconfident, and only partly.**
   - It raises inflation coverage of the 90% interval from 66% to 77% and costs from 78% to 80%
     (ensemble mean), and improves inflation CRPS.
   - It lowers coverage for ridge and for rates. The validation slice (the last quarter of each
     training window) does not represent the test years well.

   The next step is calibration on pooled out-of-sample errors from earlier folds (forward
   conformal), which should get closer to 90%.

## The Bayesian pass-through model (MCMC, `notes/macro-bayes-results.md`)

`experiments/macro_bayes.py` is a single model for all 22 target series, fitted by NUTS (NumPyro)
on each fold's training months. It uses the same data, folds and v1 climatology as the networks.

- **Oil lags:** the anchor's lags (0–12 months, or 0–2 for fuel and freight). Coefficients are
  pooled towards a mean per target group and lag length, so short series borrow from their group.
- **Momentum:** each series' last monthly change carries on (AR(1) on monthly changes). This is
  what the networks failed to use, and it is where short-horizon skill comes from.
- **Rockets and feathers:** a per-series asymmetry, so oil rises and falls can pass through with
  different strength.
- **Bands:** Student-t errors whose scale moves with:
  - recent oil volatility (every variant);
  - each series' own recent volatility, an EWMA of its past absolute changes. This is `--vol own`,
    observation-driven like GARCH, with its feedback bounded below 0.9 so it stays stationary;
  - or one drifting volatility per target group, a random walk. This is `--vol cdv`, the common
    drifting volatility of Carriero, Clark & Marcellino (2016).
  - The scale has a floor, added after the volatility terms: 5% of the series' sd, and 20% for
    policy rates, which move in discrete steps and sit still for years. Without it, the ECB
    deposit rate (flat 2016–2022) split the chains into two modes.
- **Forecasts:** simulated month by month from each series' last *published* month (so unpublished
  months are nowcast), over 400 posterior draws.
- **Two oil modes:**
  - *what-if*: the oil path that happened.
  - *forecast*: nothing after the origin is known. Oil paths are block-bootstrapped from the
    training months, scaled to oil-options implied volatility at the origin (CBOE OVX, FRED
    `OVXCLS`, from 2007-05) and centred on the WTI futures curve's slope (EIA `RCLC1`–`4`; EIA
    stopped at 2024-04, so the last 18 origins have no drift).

**Results:** run locally on 2026-10-24, 8 folds, 214 origins (2008-01 to 2025-10).
- **Convergence:** Bayes and Bayes+own-vol converged on every fold, over every sampled site with
  hyperparameters included (max R-hat ≤ 1.04, min ESS ≥ 133, no divergences).
- **Bayes+CDV did not converge** on folds 3, 6 and 7 or on the all-data fit: its latent states
  make every NUTS step hit the tree-depth limit at about 8 minutes a fold. It is left out and
  needs Iridis (`VOL=cdv` in `cluster/iridis/macro_bayes.slurm`).
- **Scoring:** skill is against the v1 climatology, over all horizons, with every row scored on
  the same folds.

| | Inflation | Unemployment | Rate | Cost |
|---|---|---|---|---|
| **Bayes+own-vol, what-if** (oil path given) | **+0.218** | −0.014 | **+0.217** | **+0.280** |
| **Bayes+own-vol, forecast** (nothing after the origin) | **+0.106** | +0.007 | **+0.207** | +0.125 |
| Bayes (oil volatility only), what-if | +0.212 | −0.014 | +0.195 | +0.264 |
| Anchored ensemble mean (what-if) | +0.119 | −0.079 | −0.136 | +0.242 |
| v1 ensemble mean (what-if) | +0.007 | +0.039 | +0.023 | +0.004 |
| 90% coverage, Bayes+own-vol what-if (target 90%) | 85% | 74% | 84% | 87% |

**Are the differences real?** These are Diebold–Mariano tests: Newey–West, 12 lags, all horizons.
- Bayes+own-vol beats the anchored ensemble on inflation (t −4.2), rates (−4.1) and costs (−2.8).
- Own volatility beats plain Bayes on rates (t −2.9) and costs (−3.8), but not on inflation (−1.2).

**Against standard benchmarks** (forecast mode, US CPI over 12 months):

| | Skill | Bayes+own-vol minus it (t) |
|---|---|---|
| **Bayes+own-vol forecast** | **+0.134** | |
| Cleveland Fed 1-year expected inflation (FRED `EXPINF1YR`) | +0.063 | −0.071 (−1.4) |
| Michigan 1-year expectations (FRED `MICH`) | −0.001 | −0.135 (−0.9) |
| Last 12-month pace carries on (random walk) | −0.143 | −0.277 (−2.0) |

- **What this means:** the forecast is on par with the Cleveland Fed's model-based expectations
  (nominally better, not significantly) and beats the random walk.
- **A caveat in our favour:** the surveys are real-time, while we're scored on revised data. That
  flatters us slightly, because seasonally adjusted CPI is revised only through its seasonal factors.

**Where the skill comes from** (what-if, all horizons; least-squares versions of the same mean
equation, `macro_bayes.py benchmarks`):

| | Momentum only | + oil lags (least squares) | Bayes | Bayes+own-vol |
|---|---|---|---|---|
| Inflation | +0.042 | +0.164 | +0.212 | +0.218 |
| Rate | +0.095 | −0.033 | +0.195 | +0.217 |
| Cost | +0.057 | +0.250 | +0.264 | +0.280 |

1. **For prices, the oil lags do most of the work.** The Bayesian layer adds about 0.05 skill on
   inflation and lifts coverage.
2. **For policy rates, pooling and fat tails turn overfitting into skill.** Least-squares oil lags
   make rates worse. Most of the gain is at 1 month (+0.31), falling to +0.15 at 12 months: rate
   cycles carry on.
3. **Horizons:**
   - With the oil path given, price skill grows with the horizon: inflation +0.11 at 1 month and
     +0.30 at 12 months, costs +0.20 and +0.36. Long-range price forecasts are mostly a question of
     the oil scenario.
   - Without it, inflation gets +0.07 to +0.16 and costs +0.11 to +0.14.
4. **The 2026 closure** (fold 7, origin 2025-09, oil path given):

   | Target | Model | 90% band | Actual |
   |---|---|---|---|
   | US CPI | ≈ +3.5% | 2.0–4.9% | +3.7% |
   | US diesel | ≈ $5.08 | up to ≈ $7.01 | $6.29 (inside) |
   | Jet fuel | +62% | +22% to +116% | +110% |

   From the calm origin 2025-03, the US CPI band (0.9–2.9) missed the actual 3.2.
5. **Responses to a ±10% Brent move** (all-data fit, mean and 90% interval of the average effect,
   12 months):
   - **Prices:** US CPI +0.37 (0.27–0.47), UK +0.35, euro area +0.44, diesel +6.2%, jet +8.4%,
     refineries +8.7%, fertiliser +6.6%.
   - **Rockets and feathers:**
     - Diesel: asymmetry +0.18 (0.05–0.32), so +6.2% for a rise but −4.7% for a fall.
     - Euro-area HICP: +0.27 (0.02–0.54).
     - Paperboard: +0.23 (0.08–0.40).
   - **36-month scenario:** the effects mostly settle within a year (US CPI +0.37 at 36 months).
   - **Unemployment** again has the wrong (demand) sign, so it isn't a what-if link.
   - **The table:** `notes/macro-bayes-responses.csv` has months 1–36. Months 13–36 are marked as
     untested scenarios, and its interval is uncertainty about the average effect only.
6. **Not solved:**
   - **Unemployment.** No model here beats the v1 ridge (+0.104). AR(1) on monthly changes can't
     tell survey noise from cycles; a latent trend component is the next thing to try.
   - **Bands.** 74–87% coverage, against 90%.
   - **Data vintages.** We score on revised data, not real-time vintages.
   - **Supply vs demand.** Oil moves aren't separated into supply and demand shocks, so the
     what-if is a conditional forecast, not a causal supply-shock effect.
   - **Joint ranges.** Series are independent given oil, so a range for a sum of series (a
     household's cost) would be too narrow.

## Flow → Brent from AIS (`notes/flow-price-link.md`)

PortWatch shows Hormuz tanker capacity at 117% of normal a week before the 2026 closure, about 0%
two weeks later, and still about 2% by late August.

| | Date | Brent | vs a week before |
|---|---|---|---|
| Closure starts (7-day share below 50% for 14 days) | 2026-03-04 | $81.56 | +14% |
| +20 trading days | 2026-04-01 | $119.56 | **+53%** |
| +120 trading days | 2026-08-25 | $88.24 | +22% |

- **Peak effect:** about **0.8% on Brent per point of lost Hormuz flow**.
- **Four months on:** about 0.27% per point. Markets adapted (stock releases, rerouting, lower
  demand) even though the flow stayed near zero.
- **Monthly regression, 2019–2026:** −0.19 ± 0.08% of Brent per point of flow. Without the
  closure months it is −0.13 ± 0.12, not significant.
- **This is one event,** and it mixes lost barrels with a risk premium. It is still the first
  data-based number for the chain's first link.

## HDI (`notes/hdi-link.md`)

On UNDP data for 1991–2022, HDI rises *with* oil prices, for both importers and Gulf exporters.
That is demand-driven comovement: oil rises in global booms, and both fell in 2020. The effect of
a 10% oil move is about 0.1 thousandths of HDI, against normal growth of 3–8 thousandths a year.
HDI is a context card, not a link in the monthly chain.

## The global one-step network (`notes/macro-global-results.md`)

`experiments/macro_global.py` fits one network shared by the 22 target series. It predicts next month's change of one series and is simulated forward like the Bayesian model. It tests whether the networks above failed because of their architecture or because of the problem they were given.

- **Why the windowed networks failed:** their validation loss was lowest after 1–2 epochs (median over seeds and folds, base sizes), so early stopping kept weights close to initialisation, which forecast like climatology. With 33–174 training origins, 1,248 inputs and about 20k–150k parameters, every later epoch fitted noise.
- **Inputs:** the series' own last 12 monthly changes, Brent's monthly change at lags 0–12, the Bayesian model's oil volatility state, and an 8-dimensional series embedding. Every (month, series) pair is a training row: 1,682 rows in fold 0 up to 5,818 in fold 7.
- **Network:** a 2-layer MLP (64 wide) with a Student-t head, whose scale sits above the Bayesian model's floor and whose tail index is at least 2.5. `global_lin` adds a per-series linear term to the location. Each variant has 5 seeds. Training stops early on the last quarter of the training months, then refits on all of them.
- **It trains:** best epochs are 3–37 from fold 2 on, and 2–8 in folds 0–1.
- **Benchmark:** per-series least squares on the same inputs (OLS), simulated the same way.

**Results:** what-if, 8 folds, 214 origins, run locally on 2026-10-24. The Bayesian reference is the fold files regenerated the same evening with the working copy of `macro_bayes.py`. Skill is against the v1 climatology, over all horizons.

| | Inflation | Unemployment | Rate | Cost |
|---|---|---|---|---|
| global | +0.272 | +0.038 | **+0.224** | +0.245 |
| global_lin | **+0.286** | **+0.055** | +0.182 | **+0.268** |
| OLS, same inputs | +0.214 | −0.016 | −0.097 | +0.187 |
| Bayes what-if | +0.212 | −0.014 | +0.195 | +0.264 |
| 90% coverage (global / global_lin / Bayes) | 85 / 82 / 84% | 74 / 77 / 72% | 86 / 85 / 83% | 85 / 83 / 85% |

1. **The shared network matches or beats the Bayesian model.**
   - Inflation: `global_lin` is better by 0.075 in scaled CRPS (Diebold–Mariano t = −2.8), and `global` by 0.061 (t = −1.9).
   - Most of the gain is at short horizons: inflation at 1 month scores +0.234 against +0.104.
   - Rates, costs and unemployment are level with Bayes (|t| < 1).
2. **The network makes the gain, not the extra lags.** OLS on the same inputs only matches Bayes on inflation, and on rates it falls apart (−0.097, t = +2.5 against Bayes). Sharing one model across the series is what makes 12 own lags usable.
3. **Oil responses are close to the validated links but about 20% smaller.** For +10% Brent, after 12 months, mean over folds (Bayes all-data fit in brackets):
   - US CPI +0.29 pp (+0.38);
   - diesel +5.0% (+6.2%);
   - jet fuel +8.1% (+8.1%).

   Unemployment and rates show small responses with no validated link, so in the what-if they stay at 0 or show a range, as before.
4. **Not solved:**
   - Unemployment still trails the v1 ridge (+0.104).
   - The network's oil response depends on the state, so a single shock table needs an all-data fit, which hasn't been run yet.
   - Coverage is still short of 90%.

### Forecast mode against the Fed and the forecasters

What-if skill can't be compared with institutions, because the what-if is given the oil path that happened. So the networks also run in a **forecast mode** (`macro_global.py forecast`), which knows nothing after the origin. Each draw follows a simulated oil path, as in the Bayesian forecast mode: a block bootstrap of training months, scaled to the OVX implied volatility and centred on the WTI futures slope.

- **Runs:** the same networks (same seeds, the same best epochs as the what-if runs) and the same 8 folds. They ran on Iridis on 2026-10-25; the surveys were fetched on 2026-10-24.
- **Headline variant:** `global_lin`, chosen on what-if skill before the forecast mode was scored.

| Forecast mode, skill | Inflation | Unemployment | Rate | Cost |
|---|---|---|---|---|
| global_lin | **+0.176** | +0.088 | +0.170 | **+0.124** |
| global | +0.165 | **+0.092** | +0.204 | +0.101 |
| Bayes own-vol | +0.106 | +0.007 | **+0.207** | +0.125 |

- **Inflation (US, UK, euro area, all horizons):** `global_lin` beats the Bayesian forecast by 0.069 in scaled CRPS (t −3.3) and the random walk by 0.199 (t −2.5). Most of the gain is at 1–3 months.

**US CPI over the next 12 months, against institutional forecasts** (`macro_global.py benchmarks`; each benchmark is compared on the origins it shares with the model):

| Benchmark | Origins | Its skill | global_lin skill | global_lin minus it (t) | global_lin CRPS lower by | Bayes own-vol minus it (t) | Bayes own-vol CRPS lower by |
|---|---|---|---|---|---|---|---|
| Cleveland Fed 1-year expected inflation (FRED `EXPINF1YR`) | 212 | +0.063 | +0.080 | −0.017 (−0.2) | 2% | −0.071 (−1.4) | 8% |
| Michigan 1-year expectations (FRED `MICH`) | 212 | −0.001 | +0.080 | −0.081 (−0.6) | 8% | −0.135 (−0.9) | 14% |
| SPF median, at each release month | 71 | +0.162 | +0.078 | +0.084 (+1.3) | −10% | +0.033 (+0.7) | −4% |
| SPF median, latest survey every month | 212 | +0.149 | +0.080 | +0.069 (+1.4) | −8% | +0.015 (+0.4) | −2% |
| Random walk (last 12-month pace) | 212 | −0.143 | +0.080 | −0.223 (−1.6) | 20% | −0.277 (−2.0) | 24% |

1. **None of our models beats the professional forecasters on US CPI over a year.**
   - The SPF median has the highest 12-month skill.
   - Our best model there is the Bayesian model, whose CRPS is 2–4% above the SPF's. `global_lin`'s is 8–10% above.
   - None of these gaps is significant (|t| ≤ 1.4).
2. **We beat the Cleveland Fed and Michigan, but not significantly.**
   - `global_lin`'s CRPS is 2% lower than the Cleveland Fed's and 8% lower than Michigan's.
   - The Bayesian model's is 8% and 14% lower (t −1.4 and −0.9).
3. **The networks' edge over the institutions is at short horizons.**
   - At 1 month, `global_lin`'s CRPS is 9% below the Cleveland Fed's (t −1.9), 7% below the latest SPF's (−1.4) and 14% below the random walk's (−2.1).
   - Over all four US CPI horizons it is 5% below the Cleveland Fed's (t −1.0) and level with the latest SPF's (1% above, t +0.1).
4. **2025 shows the gap.** In May 2025 the SPF median expected +3.0% over the next 12 months and the networks +1.8–1.9%; CPI rose 4.1%.
5. **How the SPF is aligned** (tested on synthetic data in `tests/test_macro_global.py`):
   - Each quarterly survey counts from the end of its release month, taken from the Philadelphia Fed's release-dates file: mid-February, May, August or November. The 2019Q1 survey came out in March, after a shutdown.
   - The survey forecasts the annualised growth of quarterly-average CPI, for its own quarter and the next four. Each quarter's average is placed at its middle month, and the log level is interpolated linearly in between.
   - At the usual release month, this makes the 12-month change exactly the survey's 4-quarter change from the current quarter. That window is centred on the 12 months we score.
   - Later origins move the window along the same path: 0–2 months for the "latest" row, 3 for February 2019.
   - Cleveland and Michigan are 1-year rates, so at shorter horizons they are scaled by h/12, like the random walk.
   - Every point forecast gets a Gaussian band from its own training errors.
6. **A caveat in our favour:** the surveys are real-time, while we're scored on revised data. This flatters us slightly: seasonally adjusted CPI is revised only through its seasonal factors.

## Industries by country (`notes/sector-global-results.md`)

`experiments/sector_global.py` asks whether the global one-step network works beyond the 22 macro targets. It runs the same network, training and what-if simulation on the `sectors` and `commodities` blocks.

- **Industries:** 20 of them: coal, oil and gas, metal ore mining, other mining, oil refining, chemicals, fertilisers, plastics, paper, glass and cement, cement, basic metals, iron and steel, non-ferrous metal refining and smelting, aluminium, copper, lead/zinc/tin, foundries, electricity, all manufacturing.
- **Targets:** each industry's producer prices and output in every country that publishes them for 10+ years and is still publishing. That gives 316 price and 287 output series in 35 European countries and the US.
- **Also:** 9 world mineral prices (copper, aluminium, nickel, zinc, lead, tin, iron ore, coal, uranium).
- **Size:** 612 series in one network, with 46k–159k training rows per fold (the macro run had 2k–6k).
- **Data:** Eurostat `sts_inppd_m` (domestic producer prices) and `sts_inpr_m` (output), fetched in one request each; FRED for the US (BLS PPIs, Fed industrial production) and the IMF metal prices. Fetched 2026-10-24. Publication lags are 2 months for Eurostat and 1 for FRED.
- **Variants:** `global`, `global_lin`, and `global, no oil` (the same network with its oil inputs set to 0, which measures what oil adds).
- **Benchmarks:** climatology, least squares on all 26 network inputs, and least squares on 4 of them (own last change and Brent lags 0–2).

**Results:** 8 folds, 214 origins (2008-01 to 2025-10), run locally on 2026-10-24/25, what-if. Skill is against each output's own climatology.

| | Producer prices | Output | World mineral prices |
|---|---|---|---|
| **global** | **+0.143** (t −4.7 vs climatology) | +0.033 (t −1.3) | +0.030 (t −0.7) |
| global_lin | +0.125 | +0.001 | +0.043 |
| global, no oil | +0.056 | +0.026 | +0.022 |
| Least squares, 4 inputs | +0.094 | −0.019 | **+0.090** |
| Least squares, 26 inputs | +0.010 | −0.116 | −0.150 |
| Share of series where `global` beats climatology | 94% | 69% | 61% |
| 90% coverage, `global` | 81% | 88% | 80% |

1. **Producer prices are forecastable, and oil is why.**
   - `global` beats climatology on 94% of the price series.
   - It beats the 4-input least squares (t −2.8) and the 26-input one (t −4.4).
   - Knowing the oil path adds 0.089 (t −3.0).
   - Best industries: oil refining +0.38, all manufacturing +0.26, oil and gas +0.25, iron and steel +0.18, chemicals +0.17, basic metals +0.15.
2. **Metals priced on world markets are not forecastable this way.** Metal refining and smelting (+0.03), copper (+0.04), lead/zinc/tin (+0.04) and metal ore mining (−0.01) are close to climatology. Oil adds nothing for them. Their prices follow world metal prices, which the network doesn't see; that input is the next thing to add.
3. **Output is not forecastable from its own history and oil** (+0.033, not significant), and oil adds nothing.
   - A +10% Brent move raises output by +0.3 to +0.9% in every industry. That is demand comovement, as with unemployment in the macro run, not a supply effect.
   - So output is not a what-if link.
4. **World mineral prices are best left to a small per-series model.**
   - 4-input least squares scores +0.090 against +0.030 for `global` (t +2.1).
   - The shared network is dominated by the 600 domestic series.
5. **The 26-input least squares overfits,** which is why it scored below climatology. It has 27 coefficients per series for 80–280 months. Its 90% bands cover 75–80% of outcomes, and only 8% of output series beat climatology with it.
   - The skill above is a mean of per-series ratios, and a few series where a model blows up (mostly Türkiye producer prices in 2008–10) drag it down. The report therefore also gives the median and the share of series beating climatology.
6. **`global_lin` stops training at epoch 1–3 in every fold.** Its per-series linear term (612 × 26 coefficients) overfits at once, unlike in the 22-series macro run.
7. **Responses to +10% Brent after 12 months** (`global_lin`, median over countries, US in brackets). These are unvalidated: no significance test yet.
   - **Fuels:** oil and gas prices +3.4% (+5.5%), oil refining +3.3% (+4.3%).
   - **Fertilisers and steel:** fertilisers +1.6%, iron and steel +1.4%.
   - **Non-ferrous metals:** copper +1.1%, basic metals +0.9%, aluminium +0.8%, non-ferrous metal refining +0.6%.
   - **Cement:** +0.1%.
8. **Bands are too narrow for prices,** with 81% coverage of the 90% interval, as in the macro runs.

## Specific goods by country (`notes/goods-global-results.md`)

`sector_global.py --set goods` runs the same network on the `goods`, `household` and `world` blocks:

| Group | What | Series |
|---|---|---|
| **price** | 30 European goods at the finest NACE class, 2–10 countries each (plastics in primary forms, fertilisers, cement, flat and hollow glass, paper, pulp, tyres, steel wire, aluminium, copper, sugar, flour, oils, dairy, feed); 46 US goods (BLS commodity PPIs: diesel, jet fuel, asphalt, resins, steel mill products, scrap, copper wire, cement, flour, …) | 207 |
| **output** | The 30 European goods | 153 |
| **consumer** | 15 household goods (HICP, COICOP 2018) in 37 countries: motor fuels, diesel, petrol, heating oil, gas, electricity, bread, meat, dairy, oils, sugar, rail and air fares | 508 |
| **commodity** | World Bank monthly world prices: fertilisers, grains, vegetable oils, sugar, coffee, cocoa, rubber, timber, metals, coal, gas | 53 |

- **Size:** 924 series in one network, 60k–223k training rows per fold.
- **Variants:** `global` and `global, no oil`; `global_lin` is dropped, since it overfit at once in the sector run.
- **Data notes:**
  - Eurostat's old HICP dataset (`prc_hicp_midx`) stops at 2025-12, so consumer prices come from `prc_hicp_minr`, the COICOP 2018 version, which goes back to 1996.
  - World Bank barley, sorghum and shrimp stopped before 2025, so they're left out.
  - Fetched 2026-10-24/25.
- **Run:** Iridis job 1973179 (array tasks 1973182–1973213, 2026-10-25). The laptop's five finished folds agree with it to within 0.7% CRPS (OLS and climatology exactly). They're kept in `runs/iridis/goods-1025-0141/replaced/`.

| | Producer prices | Output | Consumer prices | World prices |
|---|---|---|---|---|
| **global** | **+0.087** (t −5.8) | +0.016 (t −0.8) | **+0.151** (t −9.2) | +0.027 (t −1.7) |
| global, no oil | +0.041 | +0.008 | +0.066 | +0.012 |
| Least squares, 4 inputs | +0.060 | −0.044 | +0.069 | **+0.037** |
| Least squares, 26 inputs | −0.057 | −0.135 | −0.034 | −0.135 |
| Share of series where `global` beats climatology | 88% | 68% | 88% | 71% |
| 90% coverage, `global` | 82% | 89% | 81% | 83% |

1. **Household prices are the most forecastable group: +0.151 against climatology, 88% of series better.**
   - **Fuels:** motor fuels +0.38, petrol +0.34, diesel +0.33 and heating oil +0.35 across 22–36 countries. Almost all of that is oil: without it they score +0.00 to +0.02.
   - **Food:** cereals and bread +0.13 and dairy +0.09, from their own history, with oil adding nothing.
   - **Other energy and fares:** electricity +0.08, gas +0.12, air fares +0.08, rail fares +0.14.
   - **By horizon:** skill holds at +0.13 to +0.16 from 1 to 12 months.
   - The network beats the 4-input least squares here by 0.083 (t −7.4), and oil adds 0.073 (t −5.3).
2. **Producer prices of goods follow the sectors, but the skill is smaller** (+0.087; oil adds 0.048, t −3.5).
   - **Refined fuels:** US jet fuel +0.50, gasoline +0.48, diesel +0.46, base oils +0.35, asphalt +0.26.
   - **Petrochemicals:** organic basic chemicals +0.19 (oil adds 0.19), US resins +0.19, plastics in primary forms +0.14, US nitrogen fertilisers +0.14.
   - **Steel:** steel wire +0.16 (US +0.19).
   - **Near zero:** meat, sugar, flat glass, iron ore and recovered paper.
3. **Output again isn't forecastable** (+0.016). Food output is below climatology (sugar −0.09, oils and fats −0.07).
4. **World prices: little skill except energy-linked ones.**
   - **Positive:** LNG Japan +0.11 (oil adds 0.11, as Japanese LNG contracts are oil-indexed), coal +0.11, nickel +0.10, TSP +0.10, urea +0.09.
   - **Negative or zero:** most farm goods, and phosphate rock at −0.18.
   - The 4-input least squares is level with the network here (t +1.0).
5. **A yardstick fix in the report.** Albania's rail fares barely moved in training, so climatology's CRPS at 6 and 12 months is close to 0 and every model's ratio to it is 56–68. Those two outputs pulled consumer skill at 6–12 months from +0.15 to +0.02. The report now leaves out outputs whose climatology CRPS is below 0.05 pp and names them. No sector output is affected: the smallest there is 0.17.
6. **Responses to +10% Brent after 12 months** (`global`; median over countries). These are unvalidated.
   - **US:** jet fuel +7.9%, diesel +7.2%, asphalt +4.5%, nitrogen fertilisers +2.8%, resins +1.7%.
   - **European consumer prices:** heating oil +4.0%, diesel +3.1%, petrol +2.9%, air fares +0.7%, gas +0.1%, electricity +0.0%, bread +0.1%.
   - **European producer prices:** organic chemicals +2.0%, fertilisers +0.9%, plastics +0.5%, cement +0.1%.
   - **World prices:** urea +5.2%, rubber +3.8%, soybean oil +2.7%, palm oil and DAP +2.5%, maize and wheat +1.8%, European gas +1.1%, potash +0.2%.
7. **Bands are still too narrow for prices** (81–82% coverage of the 90% interval).

## Prices by nation (`notes/nations-global-results.md`)

`sector_global.py --set nations` runs the same network on the `nations` block, built from the World Bank's Global Database of Inflation (Ha, Kose and Ohnsorge).

- **What it holds:** monthly consumer and producer prices for ~200 economies, compiled from national sources and the IMF.
- **Vintage:** the one used, fetched 2026-10-25, ends at 2025-03. So these results stop before the 2026 closure, and they can't be updated live.
- **Coverage rule:** a country enters with 10+ years since 2000 and data from 2024 on.
- **Energy:** where a country has no energy price index, the database's energy sheet carries its housing, water, electricity, gas and other fuels index (COICOP 04, mostly rents) as a stand-in.
  - Those 95 series are a separate group, `utilities`, and never mixed with the 55 real energy indices.
  - Where a country has two rows of a measure (two sources), the one with more months since 2000 is used.
- **Size:** 496 series in 167 countries, 24k–112k training rows per fold.
- **Run:** Iridis job 1973380 (array tasks 1973381–1973422, 2026-10-25).

| | Headline | Energy | Housing and utilities | Food | Producer prices |
|---|---|---|---|---|---|
| Series (countries) | 165 | 55 | 95 | 127 | 54 |
| **global** | **+0.173** (t −9.4) | **+0.247** (t −5.0) | +0.134 (t −7.8) | +0.080 (t −3.2) | **+0.196** (t −3.6) |
| global, no oil | +0.145 | +0.068 | +0.139 | +0.101 | +0.055 |
| Least squares, 4 inputs | +0.026 | +0.179 | −0.005 | −0.025 | +0.147 |
| Least squares, 26 inputs | −0.050 | +0.086 | −0.180 | −0.160 | +0.109 |
| Share of series where `global` beats climatology | 91% | 97% | 83% | 78% | 96% |
| 90% coverage, `global` | 87% | 84% | 84% | 87% | 80% |

1. **The model works across nations.** It beats climatology on 91% of the 165 headline CPIs and on all five measures, with |t| from 3.2 to 9.4.
   - It beats the 4-input least squares on headline (t −10.1), housing and utilities and food.
   - On energy and producer prices it beats it only weakly (t −1.8 and −1.2).
2. **Oil drives energy and producer prices, not headline or food.**
   - **Energy and producer prices:** oil adds 0.182 (t −4.1) and 0.126 (t −3.2).
   - **Headline:** oil adds 0.031 (t −1.5, not significant).
   - **Food and housing:** slightly worse with oil.
   - **Advanced importers are the exception on headline:** oil adds 0.10–0.15 for the US, UK, Germany and Korea, against ~0 for most emerging economies.
3. **Gulf producers' household energy prices are administered.**
   - **Household energy:** Kuwait's energy CPI is the best-forecast series (+0.82) and Saudi Arabia's scores +0.37, with or without oil. Oil adds nothing because fuel prices there are set by the state.
   - **Importers' energy follows oil:** Germany +0.39 (oil adds 0.35), US +0.36 (0.30), UK +0.24 (0.20), South Africa +0.24 (0.21).
   - **Gulf producer prices are mostly oil:** Qatar +0.36 (oil adds 0.36), Kuwait +0.36 (0.32), Saudi Arabia +0.19 (0.26).
4. **Weak spots:**
   - Housing and utilities in some small or Central African economies (Kiribati −0.50, Congo −0.35, Cameroon −0.21).
   - Food CPIs in Taiwan, Gabon and Rwanda.
   - Food skill falls at 12 months (+0.04).
5. **Responses to +10% Brent after 12 months** (median over countries, US in brackets). These are unvalidated.
   - **Headline:** +0.4% (+0.2%; the validated US link is +0.37).
   - **Other measures:** energy +1.6% (+3.9%), producer prices +0.7% (+0.8%), food +0.6% (+0.3%), housing and utilities +0.4%.
6. **It trains, but late in the early folds:** the `global` network's best epoch is 3–12 in folds 0–1 (24k–34k rows, many countries' series start late), then 19–44.

## Reproduce

```bash
uv run experiments/macro_data.py                          # fetch, writes notes/macro-panel.md
uv run experiments/macro_nn.py check                      # tiny end-to-end run
uv run experiments/macro_nn.py fold 0                     # ... to 7; or on Iridis:
#   bash cluster/iridis/macro_env.sh; sbatch --array=0-8 cluster/iridis/macro_nn.slurm
uv run experiments/macro_nn.py ablate no_ais 0            # one diagnostic on one fold
uv run experiments/macro_nn.py final --variant v2_all     # oil-shock responses for a variant
uv run experiments/macro_nn.py report                     # notes/macro-nn-results.md
uv run experiments/macro_bayes.py check                   # tiny MCMC run
uv run experiments/macro_bayes.py fold 0 --vol own        # ... to 7, and `final`; --vol oil|own|cdv; or on Iridis:
#   VOL=own sbatch --array=0-8 cluster/iridis/macro_bayes.slurm
uv run experiments/macro_bayes.py benchmarks              # random walk, Cleveland Fed, Michigan, least-squares versions
uv run experiments/macro_bayes.py report                  # notes/macro-bayes-results.md and macro-bayes-responses.csv
uv run experiments/macro_global.py check                  # tiny end-to-end run
uv run experiments/macro_global.py fold 0                 # ... to 7 (3-11 min each locally)
uv run experiments/macro_global.py forecast 0             # ... to 7: both oil modes; or on Iridis:
#   CMD=forecast sbatch --array=0-7 cluster/iridis/macro_global.slurm   (under a minute a fold)
uv run experiments/macro_global.py benchmarks             # Cleveland Fed, Michigan, SPF, random walk (downloads the SPF files)
uv run experiments/macro_global.py ols                    # least-squares benchmark, all folds
uv run experiments/macro_global.py report                 # notes/macro-global-results.md
uv run experiments/sector_global.py check                 # tiny end-to-end run on the industries by country
uv run experiments/sector_global.py fold 0                # ... to 7 (15-52 min each locally, 3 at a time on 8 cores)
uv run experiments/sector_global.py benchmarks            # least squares on 4 inputs, all folds
uv run experiments/sector_global.py fold 0 --set goods    # ... to 7, then `benchmarks --set goods`, `report --set goods`
#   on Iridis: cluster/iridis/run.sh submit <tag> "experiments/sector_global.py fold "{0..7}" --set goods" \
#                  "experiments/sector_global.py benchmarks --set goods"; then run.sh wait <tag>
#   the same with --set nations (job 1973380), then `report --set nations`
uv run experiments/sector_global.py report                # notes/sector-global-results.md
uv run experiments/flow_price.py
uv run experiments/hdi_link.py
uv run --no-project --with pytest --with numpy --with scipy --with pandas --with xlrd --with openpyxl --with torch --with jax --with numpyro pytest -q tests
```
