# Independent verification of the knock-on modelling results

_Checked on 2026-10-24 against branch `seb/macro-nn` at commit `eda796a`. Model code was not changed. Inputs were
copied read-only from the main checkout: `data/raw/` (fetched 2026-10-24, 17:03 to 20:42 BST) and `runs/macro/`
and `runs/levy/`. The run files are: v1 folds `fold-*.json` (Iridis job 1971341, finished 2026-10-24 16:22 UTC);
`bayes-own-fold-*.json` (generated 20:17 to 20:27 UTC); `bayes-fold-*.json` (19:59 to 20:05 UTC); and
`global-fold-*.json` (local runs, 20:12 to 20:26 UTC). Every number below comes from a script in
`notes/verification/`, named next to it, run on that copy. Re-trainings ran locally on 2026-10-24 with the
model code imported unchanged. The data are real and revised (not real-time vintages); nothing is synthetic._

Skill is 1 − mean over outputs c of [mean CRPS_c / mean CRPS of the v1 climatology_c], over all horizons and the
214 test origins (2008-01 to 2025-10, 8 forward-chaining folds). All model skills are **what-if** (the realised
Brent path is given) unless marked forecast.

## Pass/fail

| # | Check | Result |
|---|---|---|
| 1 | Full test suite | **PASS**: 83 passed, 3 warnings (nested-tensor notices), 92 s |
| 2 | Leakage audit | **PASS**: all six claims hold, by index arithmetic and perturbation tests. Publication-lag residual: one series-month per fold. Its effect is 0.0000 for OLS and inside retraining noise for `global_lin`. Minor: `ea_unemp` should have lag 2, not 1 |
| 3 | Reproduction from `runs/macro/*.json` | **PASS**: every skill and DM statistic matches the notes to 3 decimals |
| 4a | Shuffled-target control: skill ≤ 0 | **FAIL as specified.** Run on all 8 folds: inflation +0.026, unemployment −0.050, rates +0.011, costs +0.007; up to +0.295 in one fold. Not leakage: the yardstick is soft. Against the shuffled model, the headline skills drop by ≤ 0.023; inflation and costs stay significant (t −2.2 to −4.7) |
| 4b | `no_change` and `climatology` baselines | **PASS**: they are what they claim. But the climatology uses only the first 54–70% of each fold's training origins |
| 5 | 2026 closure, 15 actuals | Bayes own-vol what-if: 12 of 15 inside the 90% band. Fuel means are 9–26 points low even with the real Brent path |
| 6 | Structure review | The chain is not validated end to end: flow → Brent is one event, and the Lévy Brent model is not wired in |

Discrepancies against the notes: none in `notes/macro-global-results.md` or `notes/macro-bayes-results.md`. In
`docs/macro-ensemble.md` (global section), the "Bayes what-if" row and the "t = −2.8" comparison are the **oil-vol**
Bayes variant (+0.212, t −2.81). The main model is own-vol: +0.218, t −2.56 (section 3).

## 1. Tests

`uv run --no-project --with pytest --with numpy --with scipy --with pandas --with xlrd --with openpyxl --with torch
--with jax --with numpyro pytest -q tests`: **83 passed, 3 warnings in 92.31 s**. The warnings are PyTorch
`enable_nested_tensor` notices from `experiments/macro_nn.py:152`.

## 2. Leakage audit

Script: `notes/verification/leak_checks.py`. It does index arithmetic on every fold, then runs perturbation tests.
Each test overwrites what a forecaster could not have known with 1e3 and checks that nothing downstream moves. It
also changes something the forecaster could have known and checks that the output does move, so no test passes
vacuously.

| Claim | Evidence | Result |
|---|---|---|
| Training ends before the test block, with the 12-month gap | `macro_nn.py:466-470` trains on origins `0..test[0]-13`. In every fold the last training origin's 12-month target ends the month before the first test origin. Fold 7: last training origin 2022-08, target ends 2023-08, first test origin 2023-09 (13 origins apart). `macro_bayes.py:365-367`: Bayes and global train on months 13..t0−1 (fold 7: 2001-02..2023-08) | pass |
| Standardisation uses training months only | `macro_bayes.py:108-121` (`Stats`, slices `[1:last+1]` and `[13:last+1]`) and `macro_nn.py:102-111` (`Scaler`, rows inside the inner origins' windows). Fold 7: overwriting every month after 2023-08 leaves `Stats`, `macro_global.training_rows` and `macro_bayes.design` bit-identical; changing 2023-08 does change `Stats`. Overwriting X after the last inner origin, and Y/OIL of later origins, leaves `Scaler` identical | pass |
| No input at month s contains y[s] | `macro_global.py:70-78`: own lags are y[s−1..s−12], oil z[s..s−12], volatility from z. `macro_bayes.py:139-148`: `yprev = y[s−1]`. `own_ewma` (`:129-136`) uses months before s. Perturbing y[2023-03] leaves the inputs at 2023-03 unchanged and changes the target and the next month's lags. In `macro_nn`, the features are shifted by publication lag (`macro_data.py:341`): F at 2024-06 holds US CPI's 2024-05 change and UK unemployment's 2024-04 change | pass |
| Simulators use only months published by the origin | `macro_bayes.py:301` and `macro_global.py:196` start from s0 = t − max(pub_lag) + 1. `:330` and `:218` substitute observed values only where `j ≤ −pub_lag`. Test at origins 2023-09, 2024-04 and 2025-10: every unpublished target month (s > t − pub_lag[k]) and every Brent month after t was set to 1e3. Both simulators' draws stayed bit-identical (same seed). Changing the last published month changed them. The global simulator was tested with its own OLS net; the Bayes one with least-squares posteriors plus an own-volatility term | pass |
| Early stopping uses training months only | `macro_nn.py:428-429,246`: validation is the last quarter of the training origins, 13 origins after the inner set (fold 7: 2017-06..2022-08, inner ends 2016-05). `macro_global.py:145,179-181`: validation is months above the 75% quantile of training months (fold 7: 2018-01..2023-08), then a refit on all training months | pass |
| What-if oil path starts the month after the origin | `macro_nn.py:90`: `OIL[m, j] = oil[m + j + 1]`. Checked: `OIL[test][:, 0] == oil_m[t + 1]` and `[:, 11] == oil_m[t + 12]`. Both simulators read the path from j = 1 (`macro_bayes.py:315`, `macro_global.py:203`) | pass |

**Residual risk from publication lags.** Training months run to t0 − 1, where t0 is the first test origin. At the
end of month t0, month t0 − 1 is published for every series with a lag of 1 or less. Only UK unemployment (lag 2,
`macro_data.py:103`) is not yet out. So the exposure is one series-month per fold, used to fit the model for the
first test origins.

| Re-run | What changes | Effect on CRPS |
|---|---|---|
| OLS on the network inputs, all 8 folds, **exact** information set (rows with s ≤ t0 − pub_lag[k]) (`ols_cut.py`) | the UK unemployment row only | inflation, rates, costs exactly 0.0000. Unemployment −0.0000 (t −0.01; per fold within ±0.006). Stored `global-ols.json` reproduced to 0.0 |
| OLS, all 8 folds, every series cut by max(pub_lag) = 2 months (`ols_cut.py`) | 2 months less training for all 22 series | skill: inflation +0.214 → +0.212, unemployment −0.016 → −0.015, rates −0.097 → −0.098, costs +0.187 → +0.170 (t +1.4). The cost change is all from fold 0 (+0.144 scaled CRPS; 83 training months for 26 coefficients). Other folds: within ±0.015 |
| `global_lin`, fold 7, 2-month cut (`retrain.py cut 7`) | as above, plus network retraining | mean CRPS 2.0207 → 2.0435 (+1.1%). Skill: inflation +0.028 → +0.015, unemployment −0.140 → −0.205, rates +0.069 → +0.091, costs +0.106 → +0.096 |
| `global_lin`, fold 3, 2-month cut | as above | mean CRPS 1.5265 → 1.5229 (−0.2%). Skill: inflation +0.511 → +0.507, unemployment +0.434 → +0.409, rates −0.026 → +0.121, costs +0.328 → +0.325 |
| `global_lin`, other seeds (+50), no cut (`retrain.py reseed`) | retraining noise alone | fold 7: mean CRPS 2.0207 → 1.9592 (−3.0%); skill: inflation +0.028 → **+0.089** (t −3.5), unemployment −0.140 → −0.076, rates +0.069 → **−0.015** (t +7.9), costs +0.106 → +0.123. Fold 3: 1.5265 → 1.5077; inflation +0.511 → +0.502, unemployment +0.434 → +0.469, rates −0.026 → +0.058, costs +0.328 → +0.340 |
| `global_lin`, exact information set (`retrain.py exact`) | the UK unemployment row, plus retraining | fold 7: mean CRPS 2.0207 → 2.0284 (+0.4%), same best epochs; skill: inflation +0.028 → +0.026, unemployment −0.140 → −0.166, rates +0.069 → +0.067, costs +0.106 → +0.091. Fold 3: 1.5265 → 1.5231; inflation +0.511 → +0.503, others within 0.003 |

Re-running unchanged reproduces the stored fold files bit for bit (`retrain.py base 3|7`: max |ΔCRPS| 0, and the
same best epochs). So the differences above come from the changes, not from the machine.
- **Exact information set:** the effect is nil for OLS. For the network it is at most 0.026 in skill, inside the
  retraining noise.
- **2-month cut:** it moves the network by less than a change of seeds does.
- **Verdict:** the residual risk is negligible.
- **Retraining noise:** a different set of 5 seeds moves one fold's group skill by up to 0.08. Section 6 (risk 2)
  says what that means for model comparisons.

**Minor issues found (none changes a headline number):**
- `ea_unemp` has lag 1 (`macro_data.py:115-116`). Eurostat publishes month m's unemployment at the start of month
  m + 2 (e.g. October 2024 on 2 December 2024), so lag 2 is right. The simulator treats it as known a few days
  early. The exact-cut test above covers UK unemployment only; with ea_unemp at lag 2 the exposure is one more
  series-month per fold.
- `macro_data.py:349` scales the AIS share features by their 2019–2024 mean. Folds whose training ends before 2024
  therefore see a later normalising constant. This affects only `macro_nn` (v1, skill ≈ 0), not the Bayes or
  global models, which use no panel features.
- At origin 2025-10, four 12-month targets end in October 2026, a partial month: data run to 2026-10-19/20. They are
  `uk_rate`, `ea_rate`, diesel and jet fuel. That is 4 of the 214 × 88 cells.

## 3. Reproduction

Script: `notes/verification/repro.py`. It reads the JSON files only and uses no report function. Targets and NaN
patterns are identical across `fold-`, `global-fold-`, `bayes-own-fold-` and `bayes-fold-*.json` (214 × 88).

| Model | Inflation | Unemployment | Rate | Cost | Note says |
|---|---|---|---|---|---|
| `global` | +0.272 | +0.038 | +0.224 | +0.245 | same |
| `global_lin` | +0.286 | +0.055 | +0.182 | +0.268 | same |
| Bayes own-vol, what-if | +0.218 | −0.014 | +0.217 | +0.280 | same |
| Bayes oil-vol, what-if | +0.212 | −0.014 | +0.195 | +0.264 | same |
| Bayes own-vol, forecast | +0.106 | +0.007 | +0.207 | +0.125 | same |
| v1 `nn_mean` | +0.007 | +0.039 | +0.023 | +0.004 | same |
| v1 `no_change` | −0.406 | +0.051 | +0.035 | +0.022 | (not reported) |

90% band coverage also matches. Inflation, unemployment, rates and costs: `global` 84.7 / 74.3 / 85.7 / 84.6%,
`global_lin` 81.8 / 77.4 / 85.1 / 83.2%, Bayes own-vol 84.7 / 74.5 / 84.3 / 87.4%.

**Diebold–Mariano**, per-origin mean of climatology-scaled CRPS differences, Newey–West 12 lags:

| Comparison | Inflation | Unemployment | Rate | Cost |
|---|---|---|---|---|
| `global_lin` vs Bayes own-vol | −0.070 (t −2.56) | −0.068 (t −0.58) | +0.035 (t +0.40) | +0.011 (t +0.75) |
| `global` vs Bayes own-vol | −0.055 (t −1.74) | −0.051 (t −0.47) | −0.006 (t −0.09) | +0.035 (t +1.18) |
| `global_lin` vs Bayes oil-vol | −0.075 (t −2.81) | −0.068 (t −0.57) | +0.013 (t +0.16) | −0.004 (t −0.22) |

All match `notes/macro-global-results.md` (t −2.6, −1.7, −2.8 after rounding).

**How robust is "global_lin beats Bayes own-vol on inflation" (t −2.56)?**
- **Newey–West lags** 0 / 6 / 12 / 18 / 24: t = −5.08 / −2.87 / −2.56 / −2.39 / −2.32.
- **Dropping one fold:** t ranges from −3.46 (drop fold 1) to −1.79 (drop fold 3). Mean difference by fold, 0..7:
  +0.038, +0.089, −0.099, −0.207, −0.110, −0.177, −0.017, −0.073. Bayes is better in folds 0–1 (2008-01..2012-06);
  `global_lin` is better in folds 2–5 (2012-07..2021-06).
- **By series:** UK CPI −0.118 (t −3.08) and euro-area HICP −0.158 (t −3.30) favour `global_lin`. **US CPI
  favours Bayes**: +0.070 (t +1.57).
- **By horizon:** h = 1: −0.125 (t −3.90); h = 3: −0.092 (t −2.78); h = 6: −0.030 (t −1.13); h = 12: −0.029
  (t −1.01). At the 6- and 12-month horizons the what-if slider uses, the two are level.

**Skill by fold** (against each fold's own v1 climatology; inflation | cost):

| Model | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 (2023-09..2025-10) |
|---|---|---|---|---|---|---|---|---|
| `global_lin` | +0.33 \| +0.34 | +0.16 \| +0.08 | +0.57 \| +0.37 | +0.51 \| +0.33 | +0.31 \| +0.30 | +0.25 \| +0.21 | +0.10 \| +0.26 | **+0.03 \| +0.11** |
| Bayes own-vol | +0.33 \| +0.39 | +0.33 \| +0.22 | +0.44 \| +0.35 | +0.27 \| +0.29 | +0.16 \| +0.27 | +0.04 \| +0.22 | +0.12 \| +0.21 | **−0.06 \| +0.14** |
| Bayes own-vol, forecast | +0.11 \| +0.22 | +0.09 \| −0.00 | +0.26 \| +0.27 | +0.11 \| +0.14 | +0.08 \| +0.12 | +0.07 \| +0.04 | +0.08 \| +0.08 | −0.02 \| +0.03 |

In the fold nearest the closure, inflation skill is about zero for both models, even with the oil path given.

## 4. Controls

### 4a. Shuffled targets

Script: `notes/verification/retrain.py shuffle j`. It permutes y within each series' training rows (seeded),
then trains `global_lin` exactly as `run_fold` does: same seeds, same simulation RNG. The inputs at forecast time
are the real published history. The network can only learn each series' distribution of monthly changes. It was
run on **all 8 folds** rather than 2, to get a full second zero point (`shuffle_all.py`). Best epochs are 1–2 in
every fold except fold 3 (6, 2, 2, 2, 2) and fold 5 (one seed at 5): the network finds nothing to learn.

| Shuffled-target `global_lin`, skill vs v1 climatology | Inflation | Unemployment | Rate | Cost |
|---|---|---|---|---|
| **All 214 origins** | **+0.026** | **−0.050** | **+0.011** | **+0.007** |
| fold 0 (2008-01..2010-03) | +0.097 | −0.001 | −0.006 | +0.065 |
| fold 1 (2010-04..2012-06) | +0.082 | −0.395 | −0.386 | +0.004 |
| fold 2 (2012-07..2014-09) | +0.021 | −0.279 | −0.134 | +0.104 |
| fold 3 (2014-10..2016-12) | −0.046 | +0.101 | +0.295 | −0.067 |
| fold 4 (2017-01..2019-03) | +0.082 | +0.143 | +0.211 | +0.092 |
| fold 5 (2019-04..2021-06) | +0.010 | −0.088 | +0.225 | −0.088 |
| fold 6 (2021-07..2023-08) | −0.048 | −0.043 | −0.041 | −0.054 |
| fold 7 (2023-09..2025-10) | +0.091 | −0.203 | −0.075 | +0.048 |

**Verdict: FAIL as specified.** Three of four groups score above 0 overall, by 0.007–0.026, and 16 of 32
fold × group cells are positive, by up to +0.295.

**This is not leakage:**
- The permutation breaks every link between inputs and targets.
- The forecasts read only published months (the section 2 perturbation tests).
- The positive cells are the ones where a state-blind forecast happens to suit the test block. Likely reasons (not
  tested separately): in calm rate years (folds 3–5), "almost no change, fat tails" beats a Gaussian climatology
  that is wide from the 2001–09 cycles. In fold 7, Student-t monthly draws summed over h months are sharper than the
  spread of h-month changes, and they are centred on a mean that includes 2017–23.

**What it means:** the climatology zero is about right on aggregate and soft per fold. With the shuffled-target
model as the zero point (skill = 1 − mean_c[CRPS_c / CRPS_shuffled,c]; DM t against it, 214 origins), the
headline numbers move by at most 0.023. Inflation, rates and costs stay ahead of it:

| Model | Inflation | Unemployment | Rate | Cost |
|---|---|---|---|---|
| `global_lin` | +0.267 (t −4.4) | +0.094 (t −2.0) | +0.172 (t −1.9) | +0.265 (t −4.2) |
| `global` | +0.252 (t −4.2) | +0.078 (t −2.0) | +0.214 (t −2.7) | +0.241 (t −4.6) |
| Bayes own-vol, what-if | +0.199 (t −3.0) | +0.033 (t −0.5) | +0.208 (t −6.7) | +0.277 (t −4.7) |
| Bayes own-vol, forecast | +0.083 (t −2.2) | +0.052 (t −1.1) | +0.198 (t −5.7) | +0.118 (t −3.2) |
| v1 climatology | −0.028 (t +1.7) | +0.044 (t −2.1) | −0.012 (t +0.4) | −0.008 (t +0.3) |

So the models do use the current state. The "≤ 0" check fails because the yardstick, not the model, carries a
few hundredths of skill.

### 4b. Baselines in `fold-*.json`

Script: `notes/verification/baselines.py`. It rebuilds the dataset and compares every fold's stored `climatology`
and `no_change` to what `fit_all` claims (`macro_nn.py:425-440`).
- **`climatology`**: the mean and sd of the h-month change over the **inner** training origins, constant across test
  origins. Max |Δmean| 4e-16, max |Δsd| 4e-16. Its stored CRPS equals the Gaussian CRPS of (mean, sd, y) to 5e-15.
  The stored targets equal a fresh `make_dataset` to 9e-14.
- **`no_change`**: mean exactly 0 (max |μ| 4e-15), with the same sd as the climatology. Inflation skill −0.406, as
  expected for a zero-change price forecast.
- **But "training mean and spread" means the inner set** `train[:0.75·n − 12]`. That is 33 of 61 training origins
  in fold 0 (2001-12..2004-08) up to 174 of 249 in fold 7 (2001-12..2016-05, while training runs to 2022-08). The
  yardstick misses the last 30–46% of the training origins, including the 2021–23 inflation surge in fold 7.
- **Other yardsticks**, same 214 origins:

| Climatology fitted on | `global_lin` infl. / unemp. / rate / cost | Bayes own-vol | Bayes own-vol forecast |
|---|---|---|---|
| inner origins, Gaussian (as reported) | +0.286 / +0.055 / +0.182 / +0.268 | +0.218 / −0.014 / +0.217 / +0.280 | +0.106 / +0.007 / +0.207 / +0.125 |
| all training origins, Gaussian | +0.274 / +0.068 / +0.211 / +0.250 | +0.204 / +0.002 / +0.245 / +0.262 | +0.091 / +0.022 / +0.235 / +0.101 |
| all training origins, empirical | +0.273 / +0.025 / +0.104 / +0.256 | +0.204 / −0.044 / +0.139 / +0.267 | +0.090 / −0.023 / +0.129 / +0.110 |

- The model ranking does not change.
- **Rate skill drops by about a third against an empirical climatology** (Bayes +0.217 → +0.139, `global_lin`
  +0.182 → +0.104). Policy-rate changes are mostly zero with occasional steps, which a Gaussian climatology fits
  badly.
- The stored `macro_nn` shuffle ablation (`nn_shuffle.py`), which `docs/macro-ensemble.md` cites as "skill falls
  to 0 or below", shows the same yardstick effect. The shuffled run's own climatology already scores +0.008 on
  inflation and +0.028 on costs against the unshuffled one, and shuffled `nn_mean` scores +0.006 and +0.025. So
  that claim holds against the run's own climatology, not quite against the common one.

## 5. The 2026 closure (fold 7, 12 months ahead)

Script: `notes/verification/closure.py`. Units are 100 × log change. The targets end in 2026-03, 2026-06 and
2026-09. "out" means the actual is outside the central 90% band.

| Origin | Output | Actual | Bayes own-vol what-if | Bayes own-vol forecast | `global` what-if | `global_lin` what-if |
|---|---|---|---|---|---|---|
| 2025-03 | US CPI | +3.2 | +2.0 (+0.9..+2.9) **out** | +1.8 (−0.5..+3.8) | +2.3 (+1.5..+3.2) **out** | +2.2 (+1.4..+3.2) **out** |
| 2025-03 | UK CPI | +3.2 | +2.2 (+0.2..+4.3) | +2.0 (−0.3..+4.4) | +2.2 (+0.8..+3.6) | +1.9 (+0.7..+3.2) **out** |
| 2025-03 | Euro-area HICP | +2.5 | +1.8 (−0.8..+4.1) | +1.5 (−1.7..+4.4) | +1.6 (+0.3..+2.7) | +1.6 (+0.6..+2.6) |
| 2025-03 | Diesel (GASDESW) | +31.7 | +10.6 (−5.4..+26.2) **out** | +1.7 (−34.4..+35.1) | +4.5 (−12.6..+17.9) **out** | +4.3 (−8.6..+16.9) **out** |
| 2025-03 | Jet fuel (DJFUELUSGULF) | +58.1 | +31.9 (+10.9..+52.4) **out** | +0.5 (−68.7..+56.1) **out** | +15.4 (−6.3..+40.2) **out** | +18.0 (−6.9..+43.1) **out** |
| 2025-06 | US CPI | +3.4 | +2.9 (+1.8..+4.1) | +2.1 (−0.6..+4.5) | +3.1 (+1.8..+4.5) | +3.3 (+2.1..+4.6) |
| 2025-06 | UK CPI | +2.6 | +2.8 (+0.7..+5.4) | +2.1 (−0.8..+4.9) | +3.1 (+0.9..+5.8) | +2.8 (+0.9..+5.1) |
| 2025-06 | Euro-area HICP | +2.7 | +2.3 (−0.4..+4.8) | +1.9 (−0.9..+4.9) | +2.2 (+0.4..+4.1) | +2.1 (+0.7..+4.0) |
| 2025-06 | Diesel | +33.4 | +23.9 (+3.5..+47.8) | +6.1 (−35.0..+43.9) | +18.9 (−5.6..+45.2) | +17.8 (−4.0..+44.2) |
| 2025-06 | Jet fuel | +37.3 | +18.7 (−5.3..+44.5) | −0.6 (−74.5..+63.1) | +27.3 (−11.2..+66.5) | +18.9 (−11.9..+49.4) |
| 2025-09 | US CPI | +3.6 | +3.4 (+2.0..+4.8) | +2.0 (−0.4..+3.9) | +3.5 (+2.1..+5.3) | +3.5 (+2.1..+5.1) |
| 2025-09 | UK CPI | +3.4 | +3.1 (+1.0..+5.0) | +2.2 (−0.4..+4.5) | +3.7 (+1.5..+6.6) | +3.2 (+1.4..+5.1) |
| 2025-09 | Euro-area HICP | +3.7 | +2.8 (−0.0..+5.8) | +1.8 (−1.1..+4.9) | +2.8 (+0.8..+4.9) | +2.9 (+1.3..+4.6) |
| 2025-09 | Diesel | +51.8 | +30.4 (−1.1..+62.6) | +3.6 (−31.9..+37.4) **out** | +25.0 (−2.4..+55.9) | +24.4 (+0.7..+48.6) **out** |
| 2025-09 | Jet fuel | +74.2 | +48.3 (+20.1..+77.0) | +2.2 (−77.7..+54.4) **out** | +49.6 (+8.2..+102.2) | +41.9 (+3.0..+83.3) |

Inside the 90% band: **Bayes own-vol what-if 12/15, Bayes own-vol forecast 12/15, `global` 12/15,
`global_lin` 10/15.** The Bayes columns match the table in `notes/macro-bayes-results.md`.

- **CPI:** the models are close from 2025-06 and 2025-09. From 2025-03, every what-if model misses US CPI (+3.2
  against bands topping out at 2.9–3.2).
- **Fuels:** every what-if mean is below the actual, by 9.4 to 26.1 points for Bayes own-vol and by up to 27 points
  for the global models. That happens with the realised Brent path given, so the shortfall is not oil-price
  uncertainty. Products rose more than Brent's historical pass-through implies. Widening refined-product margins
  would fit, but that was not checked here: no margin series is an input.
- **Bands:** the 2025-06 and 2025-09 bands are wide enough to catch the fuels.
- **Forecast mode:** it knows nothing after the origin, so it does not see the closure coming (fuel means +0.5 to
  +6.1). Its bands are wide enough for diesel only from the two earlier origins.
- **Overlap:** the three origins' 12-month windows overlap by 6–9 months, so these are about two independent
  looks, not 15.

## 6. Structure review

**How the chain fits together.**
1. **Flow → Brent** (`experiments/flow_price.py`, `notes/flow-price-link.md`): a monthly regression on 2019–2026
   PortWatch Hormuz flow share, plus an event study of the 2026 closure. The coefficient is −0.189 ± 0.078 with the
   closure months and −0.126 ± 0.122 without them. Brent peaked +67% above its pre-closure level; that is 0.82% per
   point of lost flow.
2. **Brent distribution** (`experiments/levy_fourier.py`, `notes/levy-fourier-results.md`): daily GARCH(1,1) with
   Student-t or CGMY innovations, tested on 2008-10..2026-10 and refitted yearly. CGMY beats Student-t by
   +0.0006 ± 0.0004 in daily log score: no real difference.
3. **Knock-ons** (`macro_bayes.py`, `macro_global.py`): the 22 monthly series, given a Brent path. The what-if mode
   takes the realised path. The forecast mode (Bayes only) takes a block bootstrap of training-month Brent changes,
   scaled to OVX and centred on the WTI futures slope (`macro_bayes.py:258-280`). **The Lévy model from step 2 is
   not used anywhere in the knock-on code.** The `oil_paths.py` / `macro_chain.py` that would connect them are not
   committed: `seb/levy-chain` is at `eda796a`, the same commit as `seb/macro-nn`. `macro_chain.py` folds were
   running on this machine while this check ran, so that link is in progress, not scored here.

**Validated out of sample:**
- **Knock-on forecasts given the realised Brent path:** 214 origins, 2008–2025 (sections 3–4).
- **Bayes forecast mode, nothing after the origin:** inflation +0.106, rates +0.207, costs +0.125. It beats the
  12-month random walk on inflation (−0.129, t −1.8, per the note). It is not significantly better than the
  Cleveland Fed expectations for US CPI (t −1.4).
- **Brent's daily to 21-day distribution:** the `levy_fourier.py` test period and rolling years.
- **The linear oil → CPI link:** fitted on 1991–2008, out-of-sample R² +0.40 on 2009–2026
  (`docs/knock-on-validation.md`).

**Not validated:**
- **Flow → Brent.** It rests on one event; without the closure the regression is not significant.
- **The composed chain.** Flow → Brent distribution → knock-ons has no end-to-end out-of-sample test.
- **The ±10% Brent responses.** These are the slider's numbers (e.g. US CPI +0.37 pp after 12 months). They are
  posterior quantities from all-data fits. The folds score forecasts given a path, not the response to a change in
  the path. Oil moves are not split into supply and demand shocks (`docs/macro-ensemble.md`, "Not solved").
- **Months 13–36 of the responses.**
- **Joint bands across series.** The series are independent given oil, so a household total would be too narrow.
- **Real-time vintages.** Everything is scored on revised data.
- **Policy rates as an oil knock-on.** The response is +0.02 pp (90% interval −0.01..+0.06) for the Fed, and the
  linear Taylor link is "unstable" across eras. Yet the pitch's demo moment moves "the expected rate".

**The three biggest risks to the claims:**
1. **Skill depends on the yardstick, most for rates and per fold.**
   - The climatology is Gaussian and fitted on the first 54–70% of training origins (4b).
   - Aggregate inflation and cost skill barely move with the yardstick: within about 0.02 against a full-training
     climatology or the shuffled-target model.
   - Rate skill drops by about 0.08 against an empirical climatology (Bayes own-vol +0.217 → +0.139).
   - Per fold, a state-blind model trained on shuffled targets scores up to +0.30 (fold 3 rates) and +0.09 (fold 7
     inflation) (4a).
   - So quote skill with its yardstick, and as a 2008–2025 average, not as a figure for any one period.
2. **"global_lin beats Bayes on inflation" is fragile, and recent skill is near zero.**
   - The t of −2.56 comes from UK and euro-area CPI at 1–3 months, in folds 2–5.
   - US CPI goes the other way (t +1.6). The 6- and 12-month horizons are level (t −1.1, −1.0). Dropping fold 3
     gives t −1.79.
   - In fold 7 (2023-09..2025-10), inflation skill is +0.03 for `global_lin` and −0.06 for Bayes own-vol, and the
     shuffled-target model does better (+0.091).
   - Seed noise is large. Re-training fold 7 with 5 other seeds moves `global_lin`'s inflation skill from +0.028
     to +0.089 and its rate skill from +0.069 to −0.015 (section 2). The DM t treats one set of seeds as fixed, so
     it understates the uncertainty in a network-vs-Bayes comparison.
   - The model variants and the "main model" were all chosen while looking at these same 214 origins; no holdout
     was left untouched.
3. **The what-if is conditional, the chain is not composed, and the bands are too narrow.**
   - All headline skill assumes the realised Brent path. Without it, inflation skill is +0.106, and fold 7 is
     −0.02 (section 3).
   - The flow → Brent step is one event.
   - 90% bands cover 74–87%.
   - In the closure, fuel prices overshot the oil-path forecast by 9–26 points (section 5).
   - So a slider that moves flow → Brent → bills shows untested links multiplied together. It needs to say which
     link is validated and which is a scenario.

## Reproduce

```bash
uv run --no-project --with numpy python notes/verification/repro.py
uv run --no-project --with numpy python notes/verification/closure.py
uv run --no-project --with numpy python notes/verification/nn_shuffle.py
uv run --no-project --with numpy --with pandas --with scipy --with xlrd --with openpyxl --with torch python notes/verification/baselines.py
uv run --no-project --with numpy --with pandas --with scipy --with xlrd --with openpyxl --with torch --with jax --with numpyro python notes/verification/leak_checks.py
uv run --no-project --with numpy --with pandas --with scipy --with xlrd --with openpyxl --with torch --with jax --with numpyro python notes/verification/ols_cut.py
# global_lin re-trainings, one fold each (40 s to 6 min): base | cut | exact | reseed | shuffle
uv run --no-project --with numpy --with pandas --with scipy --with xlrd --with openpyxl --with torch --with jax --with numpyro python notes/verification/retrain.py shuffle 7 OUT/shuffle-7.json
uv run --no-project --with numpy --with pandas --with scipy --with xlrd --with openpyxl --with torch python notes/verification/retrain_summary.py OUT
uv run --no-project --with numpy python notes/verification/shuffle_all.py OUT
```
