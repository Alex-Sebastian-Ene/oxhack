# Knock-on ensemble: regions, industry, oil, AIS and pipelines

Technical notes for the multi-region version of the knock-on chain in [design.md](design.md). It
extends the single-country links in [knock-on-validation.md](knock-on-validation.md) and the
oil-price layer in [oil-price-model.md](oil-price-model.md).

| Code | What it does | Output |
|---|---|---|
| `experiments/macro_data.py` | Fetches and aligns every input (monthly, 2000 on) with publication lags | `notes/macro-panel.md` |
| `experiments/macro_nn.py` | Deep ensemble, baselines, stacker, folds, diagnostics, oil-shock responses | `notes/macro-nn-results.md` |
| `experiments/macro_bayes.py` | Bayesian pass-through fitted by MCMC: pooled oil lags, momentum, asymmetry, volatility-state bands; what-if and genuine forecasts | `notes/macro-bayes-results.md` |
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
- **Rockets and feathers:** a per-series asymmetry, so oil rises and falls can pass through at
  different rates.
- **Bands:** Student-t errors whose scale grows with recent oil volatility. The band widens in oil
  turmoil instead of everywhere, which uniform recalibration couldn't do.
  - The scale has a floor: 5% of the series' sd, and 20% for policy rates, which move in discrete
    steps and sit still for years. Without it, the ECB deposit rate (flat 2016–2022) split the
    chains into two modes.
- **Forecasts:** simulated month by month from each series' last *published* month (so unpublished
  months are nowcast), over 400 posterior draws.
- **Two oil modes:**
  - *what-if*: the oil path that happened.
  - *forecast*: oil paths block-bootstrapped from the training months and scaled to the volatility
    at the origin. Nothing after the origin is known, so this is a genuine forecast.

**Results:** run locally on 2026-10-24, 8 folds, 214 origins (2008-01 to 2025-10). Every fold
converged: max R-hat 1.021, min ESS 190, no divergences. Skill is against the v1 climatology,
over all horizons, with every column scored on the same folds.

| | Inflation | Unemployment | Rate | Cost |
|---|---|---|---|---|
| **Bayes, what-if** (oil path given) | **+0.211** | −0.013 | **+0.182** | **+0.264** |
| **Bayes, forecast** (nothing after the origin) | **+0.105** | −0.005 | **+0.178** | +0.095 |
| Anchored ensemble mean (what-if) | +0.119 | −0.079 | −0.136 | +0.242 |
| v1 ensemble mean (what-if) | +0.007 | +0.039 | +0.023 | +0.004 |
| 90% coverage, Bayes what-if (target 90%) | 84% | 73% | 81% | 85% |

**Where the skill comes from.** Point-estimate versions of the same model, simulated with the same
code (what-if, all horizons). These were a one-off check on 2026-10-24 and aren't yet a
`macro_bayes.py` command.

| | Momentum only | + oil lags (least squares) | Bayes (MCMC) |
|---|---|---|---|
| Inflation | +0.047 | +0.166 | +0.211 |
| Rate | +0.097 | −0.032 | +0.182 |
| Cost | +0.056 | +0.250 | +0.264 |

1. **For prices, the oil lags do most of the work.** The Bayesian layer adds about 0.04 skill on
   inflation and raises 90% coverage from 79% to 84%.
2. **For policy rates, pooling and fat tails turn overfitting into skill.** Least-squares oil lags
   make rates worse, while the Bayesian version gives +0.18. Most of the gain is at 1 month (+0.26),
   falling to +0.12 at 12 months: rate cycles carry on.
3. **It forecasts without being told the oil path.**
   - Inflation +0.075 at 1 month and +0.15 at 12 months.
   - Rates +0.18.
   - Costs about +0.10 at every horizon.
   - With the oil path given, price skill grows with the horizon: inflation +0.10 at 1 month and
     +0.30 at 12 months. Long-range price forecasts are therefore mostly a question of the oil
     scenario.
4. **The 2026 closure** (fold 7, origin 2025-09, oil path given):

   | Target | Model | 90% band | Actual |
   |---|---|---|---|
   | US CPI | ≈ +3.5% | 1.3–5.3% | +3.7% |
   | US diesel | ≈ $5.01 | up to ≈ $6.58 | $6.29 (inside) |
   | Jet fuel | +61% | +21% to +118% | +110% |

   The anchored networks' diesel band stopped at $5.74.
5. **Responses to a +10% Brent move** (all-data fit, mean and 90% interval, 12 months):
   - **Prices:** US CPI +0.37 (0.26–0.49), UK +0.37, euro area +0.44, diesel +6.2%, jet +8.2%,
     fertiliser +6.3%.
   - **Rockets and feathers:**
     - Diesel: asymmetry +0.14 (0.02–0.27), so +6.2% for a rise but −5.2% for a fall.
     - Euro-area HICP: +0.28 (0.03–0.56).
     - Paperboard: +0.21 (0.05–0.38).
   - **Unemployment** again has the wrong (demand) sign, so it isn't a what-if link.
   - The per-month table for the what-if is `notes/macro-bayes-responses.csv`.
6. **Not solved:**
   - **Unemployment.** No model here beats the v1 ridge (+0.104). AR(1) on monthly changes can't
     tell survey noise from cycles; a latent trend component is the next thing to try.
   - **Bands.** They are still short of 90%, worst in 2021–23.
   - **Data vintages.** Everything is scored on revised data, not real-time vintages.

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
uv run experiments/macro_bayes.py fold 0                  # ... to 7, and `final`; or on Iridis:
#   sbatch --array=0-8 cluster/iridis/macro_bayes.slurm
uv run experiments/macro_bayes.py report                  # notes/macro-bayes-results.md
uv run experiments/flow_price.py
uv run experiments/hdi_link.py
uv run --no-project --with pytest --with numpy --with scipy --with pandas --with xlrd --with openpyxl --with torch --with jax --with numpyro pytest -q tests
```
