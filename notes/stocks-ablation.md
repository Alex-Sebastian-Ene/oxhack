# Oil stocks as inputs to the knock-on networks: ablation

_Generated on 2026-10-25 from `experiments/macro_nn.py ablate` runs on Iridis (job 1973284; 8 forward-chaining folds per variant). The `stocks` block (`experiments/macro_data.py`: US motor gasoline, distillate and total oil stocks including the SPR, EIA weekly, fetched 2026-10-25) is optional: no model uses it unless a variant asks. Data are real and revised; nothing is synthetic._

- `full` is the v1 inputs (oil, AIS, US, UK, euro area, industry) and was re-run in the same job, so every row shares the data vintage. It differs from the `full` row in `notes/macro-nn-results.md` by up to 0.03 because the panel has been re-fetched since (more 2026 months).
- `v1_stocks` adds the stocks block; `v1_fuel` adds the EIA fuel block (US crude stocks, SPR, refinery use, demand, imports, output); `v1_fuel_stocks` adds both.

**Verdict: no reliable gain.** Against `full`, the stocks move the network mixture (`nn_mean`) by +0.011 on inflation, -0.007 on unemployment, -0.025 on rates and -0.004 on costs. Next to the fuel block they move it by +0.006, +0.026, +0.026 and -0.006. Those moves change sign between groups and are the size of the seed and data-vintage noise (about 0.01-0.03). So the stocks stay out of the default inputs, as the fuel block did in the v2 runs.

## Diagnostics: what changes when one thing is removed

Reduced model set (lstm, tcn_transformer, 3 seeds, small size), skill over all horizons against the climatology of the unanchored `full` variant (same test origins for every variant, so one yardstick); folds per variant in brackets. `full` is the reference.

**Inflation**

| Variant | ridge | lstm_small | tcn_transformer_small | lstm_skip_small | tcn_transformer_skip_small | nn_mean | stack |
|---|---|---|---|---|---|---|---|
| full (8) | -0.058 | +0.017 | -0.010 | - | - | +0.004 | -0.133 |
| v1_stocks (8) | -0.051 | +0.027 | +0.001 | - | - | +0.015 | -0.152 |
| v1_fuel (8) | -0.084 | +0.016 | -0.021 | - | - | -0.002 | -0.200 |
| v1_fuel_stocks (8) | -0.077 | +0.020 | -0.015 | - | - | +0.004 | -0.245 |

**Unemployment**

| Variant | ridge | lstm_small | tcn_transformer_small | lstm_skip_small | tcn_transformer_skip_small | nn_mean | stack |
|---|---|---|---|---|---|---|---|
| full (8) | +0.107 | +0.025 | +0.038 | - | - | +0.036 | +0.056 |
| v1_stocks (8) | +0.106 | +0.029 | +0.019 | - | - | +0.029 | +0.067 |
| v1_fuel (8) | +0.070 | +0.017 | +0.023 | - | - | +0.026 | +0.021 |
| v1_fuel_stocks (8) | +0.069 | +0.041 | +0.058 | - | - | +0.052 | +0.048 |

**Rate**

| Variant | ridge | lstm_small | tcn_transformer_small | lstm_skip_small | tcn_transformer_skip_small | nn_mean | stack |
|---|---|---|---|---|---|---|---|
| full (8) | -0.261 | -0.000 | +0.026 | - | - | +0.031 | +0.018 |
| v1_stocks (8) | -0.263 | -0.010 | -0.011 | - | - | +0.006 | -0.021 |
| v1_fuel (8) | -0.376 | +0.008 | -0.023 | - | - | +0.002 | +0.068 |
| v1_fuel_stocks (8) | -0.377 | +0.018 | +0.020 | - | - | +0.028 | +0.052 |

**Cost**

| Variant | ridge | lstm_small | tcn_transformer_small | lstm_skip_small | tcn_transformer_skip_small | nn_mean | stack |
|---|---|---|---|---|---|---|---|
| full (8) | -0.085 | +0.066 | -0.017 | - | - | +0.030 | -0.005 |
| v1_stocks (8) | -0.082 | +0.056 | -0.013 | - | - | +0.026 | -0.016 |
| v1_fuel (8) | -0.119 | +0.011 | -0.010 | - | - | +0.005 | -0.032 |
| v1_fuel_stocks (8) | -0.116 | +0.005 | -0.012 | - | - | -0.001 | -0.045 |

