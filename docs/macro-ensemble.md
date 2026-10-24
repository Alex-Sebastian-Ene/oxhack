# Knock-on ensemble: regions, industry, oil, AIS and pipelines

Technical notes for the multi-region version of the knock-on chain in [design.md](design.md). It
extends the single-country links in [knock-on-validation.md](knock-on-validation.md) and the
oil-price layer in [oil-price-model.md](oil-price-model.md).

| Code | What it does | Output |
|---|---|---|
| `experiments/macro_data.py` | Fetches and aligns every input (monthly, 2000 on) with publication lags | `notes/macro-panel.md` |
| `experiments/macro_nn.py` | Deep ensemble, baselines, stacker, folds, diagnostics, oil-shock responses | `notes/macro-nn-results.md` |
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
uv run experiments/flow_price.py
uv run experiments/hdi_link.py
uv run --no-project --with pytest --with numpy --with scipy --with pandas --with xlrd --with openpyxl --with torch pytest -q tests
```
