# The chain end to end: Hormuz flow → Brent (Lévy) → knock-ons (ensemble)

Technical notes for the full chain in [design.md](design.md). Each layer has its own note:
- the Brent distribution: [oil-price-model.md](oil-price-model.md);
- the knock-on models: [macro-ensemble.md](macro-ensemble.md);
- the flow link: `notes/flow-price-link.md`.

This page covers how they join, and what the joined chain gets right.

| Code | What it does | Output |
|---|---|---|
| `experiments/oil_paths.py` | Monthly Brent paths from the daily GARCH-CGMY model, with an optional Hormuz flow scenario; backtest against the bootstrap paths | `notes/oil-paths-results.md` |
| `experiments/macro_chain.py` | Every knock-on model on the same oil draws, the ensemble, the forward-chaining backtest, and the 2026 closure replay | `notes/macro-chain-results.md`, `notes/chain-replay-2026.md`, `notes/chain-scenarios.csv` |

## How the chain is built

    lost Hormuz flow (points of normal)
      → Brent daily log returns: GARCH(1,1) with CGMY innovations, plus a scenario premium
      → monthly means of the daily path → monthly Brent log changes, 12 months ahead
      → each knock-on model simulated month by month from each series' last published month
      → an equal-weight mixture of the models' draws

1. **Flow → Brent premium.** From the 2026 closure event study, the log premium per point of lost flow:
   - ramps to log(1.67)/82 at 20 trading days;
   - decays to log(1.222)/82 at 120 days;
   - then stays flat, an assumption because the event study ends there.

   This rests on **one event**, so the link is in sample for 2026.
2. **Brent paths.**
   - Parameters come from `runs/levy/rolling-Y.json`, fitted on daily returns before 1 January of the start month's year.
   - The GARCH volatility is filtered up to the start date.
   - Daily paths use inverse-CDF sampling of the CGMY innovation. The variance is updated along each path, with the scenario's jump included, so the band widens after a shock.
   - The paths are centred, plus the futures-curve drift where it exists.
   - The knock-on panel's Brent is the monthly mean of daily spot, so the paths are turned into monthly means too. Month 0 is the start month's actual mean.
3. **Knock-on members**, fixed before scoring:
   - `bayes_own`, the Bayesian pass-through with own-volatility bands (MCMC);
   - `global_lin` and `global`, the shared one-step networks.

   Every member gets the same oil draws: draw n always uses oil path n.
4. **Ensemble.** A mixture: each draw index goes to one member, so its oil path stays paired with it. Weights chosen on earlier folds (a simplex grid) did *worse* than equal weights, so the chain uses **equal weights**.

## Backtest: 8 forward-chaining folds, 214 start points from 2008-01 to 2025-10

**The oil layer** (`notes/oil-paths-results.md`, Brent's change of the monthly mean):
- **One month ahead:** GARCH-CGMY beats the bootstrap clearly, CRPS 3.98 against 5.28 points (t −5.1). Most of the gain comes from building monthly means from the daily path: a month that rose through its last days carries into the next month's mean.
- **Three to twelve months:** level with the bootstrap; 85–89% of outcomes fall inside the 90% band.
- **Weak spot:** the downside tail is a little thin, with 9–11% of outcomes below the 5% quantile.

**The knock-on ensemble** (`notes/macro-chain-results.md`). Skill against climatology over all horizons; Newey–West t against the best single member in brackets:

| | Inflation | Unemployment | Rate | Cost |
|---|---|---|---|---|
| What-if, equal ensemble | **+0.294** (−0.7 vs `global_lin`) | **+0.084** (−0.8) | **+0.249** (−1.2 vs `global`) | **+0.302** (−2.1 vs `bayes_own`) |
| What-if, best member | +0.286 `global_lin` | +0.055 `global_lin` | +0.224 `global` | +0.280 `bayes_own` |
| Forecast with Lévy oil, equal ensemble | +0.180 | +0.102 | +0.222 | +0.147 |
| 90% coverage, what-if ensemble | 87% | 81% | 87% | 89% |

- **The ensemble is the strongest model in every group.** Against `bayes_own` it's better on inflation (t −3.8) and costs (t −2.1); against `global_lin` on costs (t −4.2).
- **Its bands are better calibrated than any member's.** Coverage is 81–89%, against 74–87% for single members.
- **The members reproduce their own earlier runs.** The networks match their `macro_global.py` folds exactly; Bayes matches within simulation noise (inflation +0.215 against +0.218).
- **Lévy oil paths help the knock-on forecasts only a little** (scaled CRPS −0.005 to −0.011, not significant). Over 1–12 months, the knock-on uncertainty is mostly the models' own, not oil's. The Lévy layer earns its place in the scenario fan, where the size of the shock drives the band.

## Independent verification

A separate audit is in `notes/verification.md` on branch `claude/silly-fermat-ac28f6`, with its scripts in `notes/verification/`. It found:

- **No leakage.** Six index and perturbation checks: training ends before each test block; standardisation and early stopping use training months only; no input contains its own target; the simulators read published months only; the what-if path starts the month after the start point. Publication lags leave at most one series-month per fold exposed, which is negligible.
- **Exact reproduction.** Every skill, coverage and Diebold–Mariano number in the notes reproduces from the run files.
- **A soft yardstick.**
  - The climatology is Gaussian and fitted on the first 54–70% of each fold's training months.
  - A network trained on *shuffled* targets scores up to +0.03 in aggregate against it, and up to +0.30 in a single fold and group.
  - Against that shuffled-target zero, the headline skills drop by at most 0.023 and stay significant for inflation, rates and costs.
  - Rate skill drops by about a third against an empirical climatology.
  - So quote skill with its yardstick, and as a 2008–2025 average.
- **Fragile single-model rankings.**
  - `global_lin` beats Bayes on inflation only at 1–3 months, through UK and euro-area CPI; US CPI goes the other way.
  - Five other seeds move one fold's skill by up to 0.08.
  - The equal-weight ensemble is the answer here: it doesn't depend on which member wins, and it beats every member.
- **Fuel overshoot in 2026.** With the real Brent path given, diesel and jet fuel rose 9–26 points more than every model expected. Product margins widened beyond Brent's historical pass-through, and no margin series is an input yet.
- **Minor:** euro-area unemployment should have publication lag 2, not 1 (`macro_data.py`). It doesn't change a headline number.

## The 2026 closure replay (`notes/chain-replay-2026.md`)

Every member is fitted on data up to 2026-01 only, then started from 2026-02, the month before the closure. The table counts 65 published outcomes: all 22 series at 1, 3 and 6 months, where published.

| Run | What it tests | Actuals inside the 90% band |
|---|---|---|
| **What-if:** the Brent path that happened | the knock-on layer on an event it never saw (**out of sample**) | **91% of 65** |
| Lost 82: GARCH-CGMY paths plus the flow scenario | how the chain composes (**in sample for the flow link**, which was calibrated on this event) | 88% of 65 |
| Lost 0: GARCH-CGMY paths, no scenario | what a forecaster without the flow link would have said | 57% of 65 |

- **US CPI after 6 months:** forecast +2.1 (+0.8..+3.8) given the real Brent path; actual +2.0.
- **UK CPI after 6 months:** +1.9 (+0.2..+3.6); actual +2.5.
- **Euro-area HICP after 6 months:** +1.7 (+0.2..+3.4); actual +2.9.
- **Fuels:** the first-month jump in diesel and jet fuel (+28 and +49) is outside the bands (+12 and +26 expected). That's the margin overshoot the audit found. From 3 months on, the bands contain the actuals.
- **Without the flow link** the chain misses the closure (57%). That's why the flow → Brent step matters, and also why it is the link to validate next: it rests on this one event.
- **The 65 outcomes aren't independent.** They come from one event and overlapping horizons, so this is one strong look, not 65.

`notes/chain-scenarios.csv` is the slider's table, from the same fits: each series' mean, median and 90% band for 0, 25, 50, 82 and 100 points of lost flow, 1–12 months ahead, with the actual where it's published. Its columns are series, group, flow_drop_points, months_ahead, mean, q05, q50, q95, actual, unit, validated, origin, source, fitted_to and generated. Unemployment and rates are marked `validated=no` (forecast only, no causal oil link). Since flow is already near zero in October 2026, a slider started today would need the *reopening* direction, which no data have tested. The demo should replay February 2026.

## Reproduce

```bash
uv run experiments/oil_paths.py check                     # oil-layer backtest
export BAYES_CHAINS=4 BAYES_WARMUP=1000                   # the sampler settings of macro_bayes.py --vol own
uv run experiments/macro_chain.py fold 0                  # ... to 7; members default to every available one
uv run experiments/macro_chain.py report                  # notes/macro-chain-results.md
uv run experiments/macro_chain.py replay                  # notes/chain-replay-2026.md, notes/chain-scenarios.csv
```
