# The chain end to end: Hormuz flow → Brent (Lévy) → knock-ons (ensemble)

Technical notes for the full chain in [design.md](design.md). Each layer has its own note:
- the Brent distribution: [oil-price-model.md](oil-price-model.md);
- the knock-on models: [macro-ensemble.md](macro-ensemble.md);
- the flow link: `notes/flow-price-link.md`.

This page covers how they join, and what the joined chain gets right.

| Code | What it does | Output |
|---|---|---|
| `experiments/oil_paths.py` | Monthly Brent paths from the daily GARCH-CGMY model, with an optional Hormuz flow scenario; backtest against the bootstrap paths | `notes/oil-paths-results.md` |
| `experiments/macro_chain.py` | Every knock-on model on the same oil draws, the ensemble, the forward-chaining backtest, and the 2026 closure replay | `notes/macro-chain-results.md` (4 members, 5 seeds), `notes/macro-chain-results-s20.md` (20 seeds), `notes/chain-replay-2026-3m.md` and `notes/chain-scenarios-3m.csv` (the recommended 3 members), `notes/chain-replay-2026.md` and `notes/chain-scenarios.csv` (4 members), `notes/macro-chain-regime.md` (the supply-disruption terms) |
| `experiments/flow_events.py` | Flow → Brent on other chokepoint events (Bab el-Mandeb 2023–24, Hormuz dips, attacks without lost flow), with placebo bands; the premium curve | `notes/flow-events.md`, `notes/flow-premium.csv` |
| `experiments/reserves.py` | Emergency stocks as a buffer: the premium curve restated per net barrel missing after releases (2026 as it happened, none, or the maximum rate until the stocks run out); stock cover by country | `notes/reserves.md`, `notes/reserve-scenarios.csv` (inputs in `notes/reserves/`); the replay under each policy (`CHAIN_RELEASE=2026|none|max CHAIN_TAG=3m-d2000 BAYES_DRAWS=2000`, Iridis job 1973501) gives `notes/chain-scenarios-3m-d2000-margins*.csv`, which the app's release choice reads |
| `experiments/macro_xattn.py` | Cross-series transformer member: one token per target series and per context series (VIX, credit spread, NASDAQ, breakevens, yields, FX), attention across them | `runs/macro/chain-*-xattn-v3.*` |
| `experiments/copula.py` | t-copula shocks across the series, fitted per fold; energy and variogram scores of joint forecasts | `notes/macro-chain-results-v3.md` |
| `cluster/iridis/macro_replay.slurm` | The 2026 replay and scenario tables on Iridis (task 0: the 3 recommended members, task 1: all four) | `notes/chain-replay-2026*.md`, `notes/chain-scenarios*.csv` |
| `cluster/iridis/macro_chain.slurm` | The chain's folds as an Iridis array; `CHAIN_SEEDS`/`CHAIN_TAG` for more networks per variant | `runs/macro/chain-*.{npz,json}` |
| `experiments/margins.py` | Refined-product margins (crack spreads) between Brent and the fuel targets, scored on the chain's own fold draws and the 2026 replay | `notes/margins-results.md`, `notes/margins-monthly.csv`, `notes/margin-scenarios.csv`, `notes/chain-fuel-scenarios-margins.csv` |
| `macro_chain.py` with `CHAIN_MARGINS=1` | The chain with the margin member on the fuel targets (`fold J margins` first) | `notes/macro-chain-results-margins.md`, `notes/chain-replay-2026-3m-margins.md`, `notes/chain-scenarios-3m-margins.csv` |

## How the chain is built

    lost Hormuz flow (points of normal)
      → Brent daily log returns: GARCH(1,1) with CGMY innovations, plus a scenario premium
      → monthly means of the daily path → monthly Brent log changes, 12 months ahead
      → each knock-on model simulated month by month from each series' last published month
      → an equal-weight mixture of the models' draws

1. **Flow → Brent premium** (`notes/flow-premium-iea.csv`, from `experiments/flow_events.py iea`; details in `notes/hormuz-flow-check.md` and `notes/flow-events.md`). The log premium per point of the IEA's lost strait flow:
   - starts at 0.25% on day 1 and rises to 0.70% on day 22;
   - decays with a 4-day half-life to a plateau of 0.51%;
   - is fitted to the observed trading days of the 2026 closure, each day divided by that day's loss by the IEA's monthly figures (89 points of February's flow in March to 47 in September), and is an assumption (flat at the plateau) beyond them.

   A scenario's premium on a day is that day's loss times the curve: a loss held for 12 months for the slider, or the IEA's 2026 path for the replay. Its 90% band comes from 2019–2025 placebo days. Each scenario path draws one standard-normal score and keeps it on every day: a split normal around the middle of the band, never below zero. So the fan carries the flow link's own uncertainty, not only oil's.

   **Why the IEA's count (switched 2026-10-25).** The curve before was fitted per point of PortWatch's trough loss (82 points held for the whole closure; `notes/flow-premium.csv`, plateau 0.39%). The IEA counts dark transits and ship-to-ship transfers too, as the chain's flow input does, and has the strait recovering to 47 points lost by September. A curve only reproduces 2026 with the loss it was fitted with, so the switch changes the curve, the replay's scenario path and the app's 2026 preset together. By the IEA's count an 82-point loss held for 12 months is harsher than 2026 was (its loss averaged 67 points), and gives a log premium of 42% after 12 months against 32% before. `experiments/reserves.py` still uses the trough curve with its 82, until it is restated on the IEA path.

   **What is validated:** the Bab el-Mandeb disruption of 2023–24 is out of sample. Scaled to Hormuz-equivalent flow, the 2026 response predicts its Brent move within noise at every horizon from 5 to 120 trading days, and it shows that rerouted barrels (63% went round the Cape) aren't lost barrels.

   **What isn't:** no other event since 2019 is large enough to test the *size*. A loss under about 26 Hormuz points can't be told from Brent's own 20-day noise. So the size still rests on 2026.

   An earlier, simpler curve (flat at 0.27% per point after 120 days) proved too low. In 2026 the premium rose again (0.70% per point in days 148–159) once the bypass pipelines' exports fell back.
2. **Brent paths.**
   - Parameters come from `runs/levy/rolling-Y.json`, fitted on daily returns before 1 January of the start month's year.
   - The GARCH volatility is filtered up to the start date.
   - Daily paths use inverse-CDF sampling of the CGMY innovation. The variance is updated along each path, with the scenario's jump included, so the band widens after a shock.
   - The paths are centred, plus the futures-curve drift where it exists: EIA stops publishing the NYMEX futures after 2024-04, so later forecasts have no drift. The EIA Short-Term Energy Outlook's Brent path was tested as a substitute and predicts Brent worse than no drift (4-month MAE 19.5 against 15.4 points after 2024-04; `notes/drift-check.md`), so zero it stays. Where both exist, the futures beat no drift by about 6% at 4 months.
   - The knock-on panel's Brent is the monthly mean of daily spot, so the paths are turned into monthly means too. Month 0 is the start month's actual mean.
3. **Knock-on members**, each fixed before it was scored:
   - `bayes_own`, the Bayesian pass-through with own-volatility bands (MCMC);
   - `global_lin` and `global`, the shared one-step MLP networks;
   - `global_tcn`, a shared one-step TCN over the last 24 months. It was tested as a fourth member and doesn't earn its place (below).
   - `xattn`, a cross-series transformer with asset-price context. It was tested as a fifth member and doesn't earn its place either (below).

   Every member gets the same oil draws: draw n always uses oil path n.
5. **Correlated shocks.** Each fold fits a t-copula to the training months' one-step residuals. Every member then draws its monthly surprises through it, so the series' surprises move together the way they did historically. Each series' own forecast stays the same.
4. **Ensemble.** A mixture: each draw index goes to one member, so its oil path stays paired with it.
   - Weights chosen on earlier folds (a simplex grid) did *worse* than equal weights, so the chain uses **equal weights**.
   - **Recommended:** `bayes_own` + `global_lin` + `global`.

## Backtest: 8 forward-chaining folds, 214 start points from 2008-01 to 2025-10

**The oil layer** (`notes/oil-paths-results.md`, Brent's change of the monthly mean):
- **One month ahead:** GARCH-CGMY beats the bootstrap clearly, CRPS 3.98 against 5.28 points (t −5.1). Most of the gain comes from building monthly means from the daily path: a month that rose through its last days carries into the next month's mean.
- **Three to twelve months:** level with the bootstrap; 85–89% of outcomes fall inside the 90% band.
- **Weak spot:** the downside tail is a little thin, with 9–11% of outcomes below the 5% quantile.

**The knock-on ensemble** (`notes/macro-chain-results.md`, `notes/macro-chain-results-s20.md`). What-if skill against climatology, over all horizons:

| | Inflation | Unemployment | Rate | Cost |
|---|---|---|---|---|
| **3 members, equal, 5 seeds** (recommended) | **+0.294** | +0.084 | **+0.249** | **+0.302** |
| 3 members, equal, 20 seeds per network (Iridis) | +0.297 | +0.081 | +0.252 | +0.306 |
| 4 members (plus `global_tcn`), equal, 5 seeds | +0.284 | +0.096 | +0.238 | +0.301 |
| Best single member, 5 seeds | +0.286 `global_lin` | +0.075 `global_tcn` | +0.224 `global` | +0.280 `bayes_own` |
| Forecast with Lévy oil, 3 members | +0.180 | +0.102 | +0.222 | +0.147 |
| 90% coverage, what-if, 3 members | 87% | 81% | 87% | 89% |

- **The 3-member ensemble is the strongest model in every group but unemployment**, where adding `global_tcn` helps (+0.096).
  - Against `bayes_own` it's better on inflation (t −3.8) and costs (t −2.1); against `global_lin` on costs (t −4.2).
  - Its bands are better calibrated than any single member's: 81–89%, against 74–88%.
- **Does each member earn its place?** Leave-one-out mixtures, all against the 4-member mixture:
  - Removing `bayes_own` hurts rates and costs (t −1.3 / −2.1).
  - Removing `global_lin` or `global` hurts inflation (t −2.8 / −2.4).
  - Removing `global_tcn` *helps* rates (t +2.0; +2.8 with 20 seeds) and inflation (t +1.1), and hurts only unemployment (t −1.8).

  So the TCN trains properly when framed as a shared one-step model (best epochs 3–14, against 1–2 for the windowed TCN in `macro_nn.py`). But it adds nothing the MLP members don't already give, except a little on unemployment.
- **Seeds:** 20 networks per variant instead of 5 raise `global` from +0.272 to +0.299 on inflation, but they move the ensembles by at most 0.006. Mixing already averages out the seed noise the audit found (up to 0.08 in one fold for a single network), so 5 seeds are enough for the ensemble.
- **Calibration:** we tried two widening rules, each chosen on earlier folds only. One uses a single factor per group; the other uses separate factors for calm and turbulent oil. Both lift unemployment coverage to 90–91%, but they make CRPS slightly worse in every group (t +1.6 to +2.7), so they are reported, not used. The bands are too wide in calm years and too narrow in crises, which a rescaling can't fix.
- **Stricter yardstick:** against the empirical distribution of all training months (the audit's recommendation), the 3-member ensemble scores +0.281 / +0.056 / +0.176 / +0.290 (inflation / unemployment / rates / costs). It is still the best model in every group.
- **Reproduction:**
  - The networks match their `macro_global.py` folds exactly; Bayes matches within simulation noise (inflation +0.215 against +0.218).
  - The `global_tcn` member run on Iridis (job 1972484) gives exactly the CRPS of the laptop runs (fold 0: 3.5813).
- **Lévy oil paths help the knock-on forecasts only a little** (scaled CRPS −0.005 to −0.011, not significant). Over 1–12 months, the knock-on uncertainty is mostly the models' own, not oil's. The Lévy layer earns its place in the scenario fan, where the size of the shock drives the band.

## The cross-series transformer and correlated shocks (`notes/macro-chain-results-v3.md`)

Run on Iridis: job 1972767 for the folds, 1972803 for the report, 1972768 for the replays (2026-10-25). All five members, every oil mode, each with independent and with copula shocks.

**`xattn`, the cross-series transformer.**
- **Tokens:** each month, one token per target series (22) and per context series (8). The context series come from FRED, fetched 2026-10-25: VIX (VIXCLS), the BAA–Treasury spread (BAA10Y), NASDAQ (NASDAQCOM), 5-year breakevens (T5YIE, from 2003), the US and UK 10-year yields, GBP/USD and EUR/USD.
- **Token inputs:** its own last 12 changes, Brent lags 0–12, the oil volatility state, an availability flag and an embedding.
- **Network:** a 2-layer, 4-head transformer (width 32) attends across the tokens of a month. Each token gets a Student-t for its next change, plus a per-token linear term. It has 19.5k parameters.
- **Simulation:** the context series are predicted too, so in a what-if only Brent's path is given.
- **A test** checks that attention picks up an effect carried by another series alone.

| What-if skill | Inflation | Unemployment | Rate | Cost |
|---|---|---|---|---|
| `xattn` alone | +0.249 | +0.072 | +0.170 | +0.229 |
| Recommended 3 (`rec`) | **+0.293** | +0.085 | **+0.250** | **+0.302** |
| `rec` + `xattn` | +0.288 | **+0.095** | +0.239 | +0.293 |

- **Alone, `xattn` is competitive:** it's better than Bayes on inflation and level with the TCN elsewhere. So attention across series trains and works in this framing.
- **But it doesn't add to the ensemble.**
  - Added to the recommended three, it makes costs worse (t +2.2) and the joint forecast worse (variogram score t +2.3).
  - It helps only unemployment (t −1.2).
  - In the 2026 replay it lowers the what-if coverage from 89% to 86%; all five members together get 83%.
- **Our reading:** at a 1–12-month horizon, the asset-price context carries little beyond what Brent and each series' own history already give. And about 280 months aren't enough to learn the cross-series interactions reliably.

**Correlated shocks: the t-copula.**
- **Fit:** per fold, rank normal scores of each series' one-step residual (momentum and oil lags), their correlation shrunk 20% towards the identity, and the tail index by maximum likelihood.
- **What it finds:** small correlations on average (mean absolute 0.07–0.11) with a few strong pairs (up to 0.60–0.68). The tail index is 8–30.

| Recommended 3, mean over origins and horizons | Energy score | Variogram score |
|---|---|---|
| What-if, independent → copula | 4.489 → 4.481 (t −2.1) | 68.36 → 67.97 (**t −3.3**) |
| Forecast with Lévy oil, independent → copula | 4.993 → 4.988 (t −1.1) | 72.12 → 71.83 (**t −2.3**) |

- **The variogram score improves for every member and every ensemble** (t −1.5 to −4.3). That's the score that checks whether the series' relative moves are right. The energy score barely moves, as expected, because it's known to be insensitive to dependence.
- **Each series' own CRPS is unchanged**, within simulation noise.
- **So the copula makes the joint answers more coherent at no cost to any single series.** That matters for anything that adds series together, such as a household bill or a basket of costs.
- **In the single 2026 replay** the joint scores are mixed: slightly worse at 1 and 3 months, better at 6. One event can't settle it; the folds do.

**Recommended model now:** the 3-member equal ensemble (`bayes_own`, `global_lin`, `global`) with copula shocks, plus the margin member on the three fuel targets (`CHAIN_MARGINS=1`; see "Refined-product margins" below). The supply-disruption terms (`bayes_regime`) were tested and not adopted; see "Supply-disruption terms" below.

## Independent verification

A separate audit is in `notes/verification.md` on branch `seb/knock-on-verification`, with its scripts in `notes/verification/`. It found:

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

## The 2026 closure replay (`notes/chain-replay-2026-3m.md`)

Every member is fitted on data up to 2026-01 only, then started from 2026-02, the month before the closure. The table counts 65 published outcomes: all 22 series at 1, 3 and 6 months, where published. The numbers below are for the recommended 3 members, refitted on Iridis with the IEA premium curve (`notes/flow-premium-iea.csv`; job 1974021, and 1974022 with the margin member). Adding `xattn` (`notes/chain-replay-2026-4x.md`) gives what-if 86% and scenario 94%; all five members (`notes/chain-replay-2026.md`) give 83% and 94%. Each replay note also has the joint scores with and without copula shocks.

| Run | What it tests | Actuals inside the 90% band |
|---|---|---|
| **What-if:** the Brent path that happened | the knock-on layer on an event it never saw (**out of sample**) | **89% of 65** (91% in the laptop fit) |
| IEA 2026: GARCH-CGMY paths plus the flow scenario of 2026 as the IEA counts it, month by month | how the chain composes (**in sample for the flow link**: the premium curve was fitted to this event) | 95% of 65 (97% with the trough curve and 82 points held; 88% with the first, simpler curve) |
| Lost 0: GARCH-CGMY paths, no scenario | what a forecaster without the flow link would have said | 58% of 65 |

- **The IEA switch** (2026-10-25) changes only the scenario run: the what-if and lost 0 don't use the premium, and reproduce exactly. Its mean scaled CRPS improves from 0.615 to 0.600, with slightly narrower bands.
- **Laptop versus Iridis:** the what-if difference is one of 65 outcomes crossing its band edge. The Iridis refit lands slightly differently from the laptop's, most likely in the MCMC fit; means move by 0.1–0.5 points. The networks themselves reproduce exactly across machines.
- **The scenario's wider coverage is partly bought with wider bands.** Each path carries the flow link's own uncertainty. US CPI after 6 months: +2.6 (−0.3..+6.8) under the IEA 2026 scenario, against +2.1 (+0.8..+3.8) given the real Brent path; actual +2.0. Diesel after 1 month: +13.8 (+1.7..+29.1) contains the actual +27.9, and jet fuel +29.6 (+3.2..+62.7) contains +49.1, where the what-if misses both.

- **US CPI after 6 months:** forecast +2.1 (+0.8..+3.8) given the real Brent path; actual +2.0.
- **UK CPI after 6 months:** +1.9 (+0.3..+3.6); actual +2.5.
- **Euro-area HICP after 6 months:** +1.7 (−0.2..+3.3); actual +2.9.
- **Fuels:** the first-month jump in diesel and jet fuel (+28 and +49) is outside the bands (+12 and +26 expected). That's the margin overshoot the audit found. From 3 months on, the bands contain the actuals.
- **Without the flow link** the chain misses the closure (58%). That is why the flow → Brent step matters. Its sign and the role of rerouting now have an out-of-sample check (Bab el-Mandeb 2023–24), but its size still rests on this one event.
- **The 65 outcomes aren't independent.** They come from one event and overlapping horizons, so this is one strong look, not 65.

`notes/chain-scenarios-3m.csv` is the slider's table, from the same fits (`notes/chain-scenarios.csv` is the all-member version, `-3m-margins` the app's): each series' mean, median and 90% band for 0, 25, 50, 82 and 100 points of lost flow held for 12 months, 1–12 months ahead, with the actual where it's published. `notes/chain-scenarios-2026-3m.csv` (and `-margins`) has the same columns for the IEA's 2026 path, `flow_drop_points` = `iea_2026_path`: that, not 82 held, should be the app's 2026 preset (handed to the UI lane). The stock-release replays (`*-3m-d2000-margins*`, `experiments/reserves.py`) still use the trough curve and wait to be restated on the IEA path. Its columns are series, group, flow_drop_points, months_ahead, mean, q05, q50, q95, actual, unit, validated, origin, source, fitted_to and generated, plus the effect columns in the `-margins` tables (below). Unemployment and rates are marked `validated=no` (forecast only, no causal oil link). Since flow is already near zero in October 2026, a slider started today would need the *reopening* direction, which no data have tested. The demo should replay February 2026.

**The effect of a scenario, draw by draw.** The app shows what the lost flow *adds* against no disruption. Taking the scenario's band minus the 0-point mean overstates that range: it also carries the ordinary forecast spread. So the scenarios now share every random number, draw by draw (2026-10-25):
- **Oil paths:** the premium's band score is drawn for every scenario, 0 points and the IEA's 2026 path included, after the daily shocks (`oil_paths.monthly_paths`; `lost=None`, the folds' default, draws exactly what it did before).
- **Members:** their Student-t noise comes from one uniform per value (`macro_chain.PairedRNG`). numpy's own sampler uses a varying number of random numbers per draw, and the networks' tail index moves with oil, so before this the scenarios fell out of step.
- **Margin member:** one seed for every scenario, and a 0-point scenario carries its crisis at scale 0, so it picks past crises from the same random numbers (`margins.known_events`).
- **Not yet paired:** `bayes_gas` (not adopted) still seeds its gas paths per scenario, so a replay with it is paired except in the gas channel. The stock-release tables (`*-3m-d2000-margins*`) compare policies on the same random numbers and become fully paired when they are next run.

`notes/chain-scenarios-3m-margins.csv` and `notes/chain-scenarios-2026-3m-margins.csv` add `effect_mean`, `effect_q05`, `effect_q50` and `effect_q95` after `q95`: the scenario's draw minus the 0-point draw with the same index. They are 0 at 0 points.
- **Pairing works:** the 0- and 25-point draws correlate at a median of 0.967 (minimum 0.874 over the 88 outputs). Before, the 0-point oil paths were unrelated to the others (correlation −0.05 with 82 points).
- **The effect bands are narrower than the subtracted ones,** most of all for small shocks. On the app's series at 3 and 12 months, their 90% width is 0.23–0.48 of the old one at 25 points and 0.60–0.89 at 82–100 points.
  - US CPI after 12 months at 82 points held: +2.7 (−0.4..+8.7), against +2.5 (−2.0..+10.4) the old way.
  - The IEA's 2026 path against no disruption, US CPI after 12 months: +2.0 (−1.5..+8.2).
- **What stays wide** is the shock's own uncertainty:
  - the premium's band (0.08–1.31% per point, averaged over 12 months);
  - the GARCH feedback: the jump raises Brent's volatility, which deepens falls as well as rises. About a tenth of paired Brent draws at 82 points held end below no disruption after 12 months.
- **What else moved:**
  - The what-if column reproduces exactly (89% of 65, the same joint scores).
  - The scenarios' means moved within simulation noise (median 0.02 of their 90% width, at most 0.09).
  - In the margins replay, lost 0 now covers 57% of 65 (58% before) and the IEA 2026 run 98% (95% before).
  - With 400 draws, the fuels' 12-month band edges are noisy. On the trough curve, a bootstrap put the standard error of diesel's 95% edge at about 13 log points and jet fuel's at 16, against 0.8 for US CPI.
- **Run:** Iridis job 1974232 (`oxhack-paired-iea`), from this code on the IEA curve, 2026-10-25. Jobs 1974181 and 1974208 ran the same edits on the trough curve.

## Refined-product margins (`notes/margins-results.md`)

The fuel targets were driven by Brent alone, and in 2026 they rose 9–26 points more than every member expected. `experiments/margins.py` puts product prices between Brent and those targets.

- **Data:** daily EIA spot prices: New York Harbor ULSD (New York Harbor heating oil before 2006-06), US Gulf Coast jet fuel, US Gulf Coast conventional gasoline and Los Angeles RBOB. Crack spread = product − Brent in $/bbl, monthly means, in `notes/margins-monthly.csv`.
- **Margin model,** per product, on the log ratio r = log(product / Brent):
  - reversion to the five-year mean (half-life 2–3 months);
  - a sticky-dollar response to Brent, and seasonality;
  - Brent volatility widens the band;
  - a crisis term: the excess margin path after each earlier IEA collective action (1990, 2005, 2011, 2022). Each draw takes one past crisis.
- **Into the chain:** each fuel target maps onto its products:
  - jet fuel spot is an identity;
  - retail diesel follows New York Harbor ULSD at lags 0–1;
  - the refinery PPI follows diesel, gasoline and jet.

  The **margin member** is that mapping driven by Brent path n plus a simulated margin path. It is mixed in as a fourth, equal-weight member for the three fuel targets only.

Fuel targets on the 8 folds (skill against the v1 climatology, all horizons, the three targets together; Iridis jobs 1972719–1972727):

| | What-if | Forecast (Lévy oil) |
|---|---|---|
| Chain (3 members) | +0.562 | +0.154 |
| **+ margin member** | **+0.611** (t −3.8; better in 8 of 8 folds) | **+0.179** (t −3.5; 7 of 8) |
| + the same member on a neutral margin | +0.596 | +0.168 |
| Margin news added to the chain instead | +0.557 | +0.159 |

- **Where the gain comes from:**
  - Most of it is structure: about two thirds given the real Brent path, and half with Lévy oil. The members pass fuel prices through from Brent too weakly (jet fuel +8.4 for +10% Brent at 12 months in Bayes), while jet fuel spot is Brent plus its margin by definition.
  - The margin's own state (its gap to the five-year mean, its season, crises) adds the rest, mostly from 2019 on.
  - Adding the margin as a correction to the members' draws helps from 2019 on and hurts in 2008–2016, so it isn't used.
- **2022 (out of sample in fold 6, trained to 2021-06):** the earlier crises' term is far too weak. The diesel crack reached $82/bbl in May 2022 against a forecast of $20 (4..40).
- **2026 (out of sample in the replay, trained to 2026-01; 2022 is in sample there):** the overshoot after 1 month shrinks only a little.
  - Jet fuel: +23.2 → +21.6 points.
  - Retail diesel: +15.9 → +15.3.
  - Refinery PPI: +6.6 → +5.9.

  The 1-month bands still miss diesel and jet fuel. The replay catches the same 89% of 65 with or without the margin member.

  The reason the overshoot barely moves: the diesel crack went from $34 to $63 in March 2026. The average of the four earlier crises gives $39 (23..56); only 2022 widened margins on this scale.
- **Scenario:** `notes/margin-scenarios.csv` gives the crack fan for 0–100 points of lost flow from 2026-02.
  - The crisis term is scaled by lost flow / 82, an assumption.
  - It comes in two versions: the pre-2026 crises (validated against 2026), and with 2026's own path added (in sample, for a forward scenario).
  - `notes/chain-fuel-scenarios-margins.csv` gives the fuel targets with the margin member, in the columns of `notes/chain-scenarios-3m.csv`.
- **In the chain, behind a flag.** `macro_chain.py fold J margins` saves the margin member's draws like any member's (`runs/macro/chain-J-margins.npz`; the fuel targets only).
  - With `CHAIN_MARGINS=1`, `report` and `replay` add it to every mixture of two or more members, as one more equal-weight member on the three fuel targets' columns.
  - Outputs are tagged `-margins`. Single-member columns and the other 19 targets are untouched.
  - Its draws match `margins.py`'s exactly, and they come from the same oil paths, draw by draw.

  Results for the recommended 3 members (`notes/macro-chain-results-margins.md`, against the same report without the flag):

  | Cost group, equal mixture | Without | With the margin member |
  |---|---|---|
  | What-if | +0.302 | **+0.313** |
  | Lévy oil (forecast) | +0.147 | **+0.153** |
  | Bootstrap oil (forecast) | +0.138 | **+0.143** |
  | What-if, against the stricter empirical yardstick | +0.290 | **+0.301** |

  Inflation, unemployment and rates are unchanged by construction, and cost coverage stays at 89%.

  The replay with it is `notes/chain-replay-2026-3m-margins.md` (Iridis job 1972934; rerun on the IEA curve with paired scenario draws as job 1974232, which leaves the what-if unchanged), the same fits as `notes/chain-replay-2026-3m.md`. Its joint energy score of all series after 1 month is lower: 3.60 against 3.70 with independent shocks, 3.66 against 3.78 with copula shocks. It is about level at 6 months. The slider's table with it is `notes/chain-scenarios-3m-margins.csv`: the same columns plus the effect columns (above). Since the paired rerun, its non-fuel rows differ from `notes/chain-scenarios-3m.csv` within simulation noise.
  - The copula leaves each series' own distribution unchanged, so the cost-group numbers above hold for the recommended model with copula shocks too.
  - The margin member's draws carry their own shocks; they are not drawn through the copula.

## Supply-disruption terms: tested, not adopted (`notes/macro-chain-regime.md`)

The cost-of-living model (`docs/cost-of-living.md`) adds two terms in months of a physical supply disruption, D = 1 (2022-03..2022-12 and 2026-03..2026-12). `bayes_regime` adds them to `bayes_own`:
- the oil term is multiplied by 1 + κ, with κ pooled by target group;
- the error scale is multiplied by exp(ζ), so the band widens in disruption months only, the calm-versus-crisis gap that a single rescaling can't fix.

After the origin, D is the calendar in the what-if, D at the origin carried on in the forecasts, and on in a flow scenario of 25 points lost or more (about 5 mb/d, more than Russia lost in 2022). It is only fitted when named, and a fit whose training holds no disruption leaves both terms out.

**The test** compares `rec_regime` (`bayes_regime`, `global_lin`, `global`) with the recommended `rec`. All four members were refitted on Iridis with the same code and seeds. The keep rule was fixed before scoring: no group worse beyond 2 Newey–West errors on the folds (what-if and levy), and a better replay in the lost-82 run (lower mean scaled CRPS, coverage no lower). The cost-of-living session's extra checks are reported beside it: inflation and cost both better in lost 82, and the what-if row agreeing in sign.

- **The folds can barely test it.** Only fold 7's training (to 2023-08) holds a disruption, so on folds 0–6 `bayes_regime` is `bayes_own`, draw for draw. On fold 7, 8 what-if origins and no forecast origin have D = 1 ahead. No group is worse (largest t +1.3, inflation, member alone); the ensemble differences are within ±0.005.
- **The 2026 replay** (fitted to 2026-01, so κ and ζ come from 2022 alone), scaled CRPS over 65 published outcomes:

  | Run | `rec` | `rec_regime` | Coverage |
  |---|---|---|---|
  | What-if (realised Brent, calendar D) | 0.636 | **0.598** | 89% → 94% |
  | Lost 82 (Lévy paths + flow premium, scenario D) | 0.615 | **0.613** | 97% → 97% |
  | Lost 0 (forecast, D = 0) | 1.174 | 1.171 | 58% → 58% |

- **By group, the gain is all costs and unemployment.** Costs improve in both runs (−0.062 what-if, coverage 82% → 90%; −0.022 lost 82). Inflation improves slightly in the what-if (−0.010) but worsens in lost 82 (+0.068). Rates worsen in both (+0.018, +0.023): their disruption band factor is ×1.9–3.4, though oil doesn't drive rates.
- **The member alone is worse in the replay:** `bayes_regime` scores 0.647 against `bayes_own`'s 0.641 in the what-if, and 0.685 against 0.602 in lost 82. So the ensemble's what-if gain, which comes with coverage rising from 89% to 94%, is the mixture's wider spread, not a sharper member.
- **Why inflation overshoots:** learned from 2022, the CPI multiplier 1 + κ is 2.8–2.9. Like for like, the cost-of-living model's own fit to 2026-02 (κ from 2022 only) gives about 2.0–2.1 for headline CPI: 2.07 US, 1.99 UK, 2.04 euro area (`notes/cost-of-living.md` on branch `seb/col-split`, Iridis job 1973560; not yet on `main`). Its all-data fit, which includes 2026 (job 1973565), gives 1.51 / 1.50 / 1.58. Its 2022-only cost multipliers are close to the chain's: diesel 1.47, jet fuel 1.12, refineries 1.28. So both overshoot when they learn from 2022 alone, and the chain more. A likely reason: `macro_bayes.py` takes Brent alone, with no gas input, so its κ also absorbs 2022's gas-driven inflation, which the cost-of-living model gives to its gas terms. Over 12 months of a scenario, that overshoots 2026.
- **Verdict: tested, not adopted (2026-10-25).** It passes the agreed rule narrowly (0.615 → 0.613 is within the noise of one replay), but fails the reviewer's inflation check. **The recommended model stays `rec`.** The code stays, off unless named (`bayes_regime`), as a documented result. Eight origins and one replay are thin evidence either way.
### The cost-only variant: post hoc, not adopted until a recheck

**Post hoc: chosen after seeing the 2026 replay above.** `bayes_regime_cost` puts κ and ζ on the cost group (the `ind_*` series) only, where `bayes_regime` helped in both runs and its fuel multipliers are close to the cost-of-living model's. Inflation, unemployment and rates are modelled as in `bayes_own`. It ran on Iridis on the same folds, seeds and replay (jobs 1973890 and 1973891).

- **Folds:** on folds 0–6 its draws are `bayes_own`'s exactly. Fold 7 shows no harm in any group (all |t| ≤ 1.4).
- **Replay, horizons 1–6** (the outcomes it was chosen from, so not a test), `rec` against `rec_regime_cost`:

  | Run | `rec` | `rec_regime_cost` | Coverage |
  |---|---|---|---|
  | What-if | 0.636 | 0.603 | 89% → 94% |
  | Lost 82 | 0.615 | 0.602 | 97% → 98% |
  | Lost 0 (terms inactive) | 1.174 | 1.175 | 58% → 55% |

- **By group:** costs improve in both runs (−0.056 what-if, coverage 82% → 90%; −0.023 lost 82). The other groups move by at most 0.008 (inflation +0.008 in both runs). Their model is unchanged, so that can only be Monte Carlo noise from a separate MCMC run. For the same reason the lost-0 row, where D = 0 and the terms can't act, moves by +0.001 in CRPS and 3 points in coverage (2 of 65 outcomes).
- **The member alone, and accuracy against spread** (cost group; the median's absolute error and the 90% band's width, both divided by the training spread):

  | Run | Model | Cost CRPS | Median error | Band width | Coverage |
  |---|---|---|---|---|---|
  | What-if | `bayes_own` → `bayes_regime_cost` | 0.898 → 0.762 | 1.219 → 1.048 | 3.19 → 4.33 | 69% → 82% |
  | What-if | `rec` → `rec_regime_cost` | 0.874 → 0.818 | 1.195 → 1.169 | 3.56 → 4.07 | 82% → 90% |
  | Lost 82 | `bayes_own` → `bayes_regime_cost` | 0.828 → 0.785 | 1.157 → 1.017 | 4.62 → 6.19 | 90% → 92% |
  | Lost 82 | `rec` → `rec_regime_cost` | 0.826 → 0.803 | 1.161 → 1.138 | 5.10 → 5.69 | 95% → 97% |

  Unlike `bayes_regime`, the member is better on its own: its median is 12–14% closer, as well as its band about 35% wider. So the gain is not only the mixture's. Inside the ensemble the median moves only 2% closer while the band widens 12–14%, so there most of the CRPS gain is the wider band.
- **Multipliers** match `bayes_regime`'s on every cost series within 0.02 (diesel 1.55, jet fuel 1.14, refinery PPI 1.31).
- **The recheck:** the chain's horizons are 1, 3, 6 and 12 months, so the next outcomes are the 12-month changes, complete with 2027-02 data. None are published yet. When they are, refresh the data and re-run `macro_chain.py regime`: it recomputes the replay's outcomes from the current data and scores horizons 1–6 and 12 apart. Those 12-month outcomes are the only test this variant can get.
- **Status: not adopted.** `rec` stays recommended until that recheck.

## A gas channel: tested, not adopted (`notes/macro-chain-gas.md`)

Hormuz also carries about a fifth of the world's LNG, and in 2022 the disruption terms' oil multiplier absorbed gas-driven inflation. `bayes_gas` adds each series' regional gas price to `bayes_own` as a second driver: Henry Hub (FRED `MHHNGSP`) for the US series and the US industry costs, the IMF EU gas price (`PNGASEUUSDM`) for the UK and euro area, lags 0–12, pooled like the oil lags. The what-if is given the gas that happened; a forecast draws gas along each oil path (beta × Brent plus each price's own GARCH-t noise; betas 0.21 and 0.07). The keep rule, fixed before scoring: no group worse beyond 2 Newey–West errors on the folds, a lower fold CRPS over all outputs in the what-if, and a 2026 replay what-if no worse.

- **Folds** (all 214 origins have gas data, so this is a real test; `bayes_own` refitted alongside reproduces its earlier run exactly; job 1974005): costs improve (ensemble t −3.1 what-if, −3.5 levy), inflation doesn't move, unemployment and rates get worse (rates t +2.3 in levy and bootstrap). Over all outputs, −0.003 (t −1.7).
- **The 2026 replay** (job 1974025): worse in the what-if, 0.664 against 0.636, with inflation 0.427 against 0.392 even though EU gas rose; coverage the same.
- **Verdict: not adopted.** The gas data add to the industry costs, as the disruption terms did, but not to the series the app leads with. The code stays, off unless named.

## Reproduce

```bash
uv run experiments/oil_paths.py check                     # oil-layer backtest
export BAYES_CHAINS=4 BAYES_WARMUP=1000                   # the sampler settings of macro_bayes.py --vol own
uv run experiments/macro_chain.py fold 0                  # ... to 7; members default to every available one
uv run experiments/macro_chain.py report                  # notes/macro-chain-results.md
uv run experiments/macro_chain.py replay                  # notes/chain-replay-2026.md, notes/chain-scenarios.csv
CHAIN_MEMBERS=bayes_own,global_lin,global CHAIN_TAG=3m uv run experiments/macro_chain.py replay   # the recommended 3
CHAIN_TAG=s20 uv run experiments/macro_chain.py report    # after the 20-seed Iridis run below
CHAIN_TAG=v3 uv run experiments/macro_chain.py report     # five members, independent and copula shocks (notes/macro-chain-results-v3.md)
uv run experiments/margins.py data                        # EIA spot prices -> notes/margins-monthly.csv
uv run experiments/margins.py fold                        # all 8 folds, against runs/macro/chain-J-<member>.npz
uv run experiments/margins.py replay                      # the 2026 replay (refits the 3 members once, then cached)
uv run experiments/margins.py report                      # notes/margins-results.md and the scenario CSVs
uv run experiments/macro_chain.py fold 0 margins          # ... to 7: the margin member's draws (numpy only, seconds)
CHAIN_MARGINS=1 CHAIN_MEMBERS=bayes_own,global_lin,global uv run experiments/macro_chain.py report   # -> -margins
CHAIN_TAG=regime uv run experiments/macro_chain.py regime  # notes/macro-chain-regime.md, after the regime runs below
uv run experiments/macro_chain.py gas                     # notes/macro-chain-gas.md, after the gas runs below
uv run experiments/macro_bayes.py drift                   # notes/drift-check.md: futures, STEO or no drift
```

On Iridis (`docs/iridis.md` for access). Copy `experiments/`, `cluster/`, `scripts/`, `data/raw/`, `notes/industry/` and `runs/levy/` to a fresh `/scratch/$USER/<folder>`, then:

```bash
bash cluster/iridis/macro_env.sh                                       # once (torch, jax, numpyro)
sbatch --array=0-7 cluster/iridis/macro_chain.slurm                    # every member, 5 seeds
CHAIN_SEEDS=20 CHAIN_TAG=s20 sbatch --array=0-7 --time=08:00:00 cluster/iridis/macro_chain.slurm
CHAIN_TAG=v3 sbatch --array=0-7 --time=04:00:00 cluster/iridis/macro_chain.slurm   # five members, with copula shocks
sbatch --array=0-2 cluster/iridis/macro_replay.slurm                     # the replays: rec, all, rec + xattn
sbatch --array=0-8 cluster/iridis/margins.slurm                        # margins: folds 0-7, task 8 the replay
MEMBERS=margins sbatch --array=0-7 cluster/iridis/macro_chain.slurm    # the margin member in the chain
CHAIN_MARGINS=1 sbatch --array=0 cluster/iridis/macro_replay.slurm     # the 3-member replay with it
MEMBERS="bayes_own bayes_regime" CHAIN_TAG=regime sbatch --array=0-7 cluster/iridis/macro_chain.slurm   # the regime test
MEMBERS="global_lin global" CHAIN_TAG=regime sbatch --array=0-7 cluster/iridis/macro_chain.slurm
CHAIN_MEMBERS=bayes_own,bayes_regime,global_lin,global CHAIN_TAG=regime sbatch --array=1 --time=03:00:00 cluster/iridis/macro_replay.slurm
MEMBERS=bayes_regime_cost CHAIN_TAG=regime sbatch --array=0-7 cluster/iridis/macro_chain.slurm         # the cost-only variant
CHAIN_MEMBERS=bayes_regime_cost CHAIN_TAG=regimecost sbatch --array=1 cluster/iridis/macro_replay.slurm
MEMBERS="bayes_own bayes_gas" CHAIN_TAG=gas sbatch --array=0-7 cluster/iridis/macro_chain.slurm         # the gas channel
CHAIN_MEMBERS=bayes_own,global_lin,global CHAIN_TAG=3m sbatch --array=1 cluster/iridis/macro_replay.slurm   # the replays on the IEA curve
CHAIN_MEMBERS=bayes_own,global_lin,global CHAIN_TAG=3m CHAIN_MARGINS=1 sbatch --array=1 cluster/iridis/macro_replay.slurm
CHAIN_MEMBERS=bayes_gas,global_lin,global CHAIN_TAG=3m-gas sbatch --array=1 cluster/iridis/macro_replay.slurm
```
Copy `notes/` up as well for the replays: they read `notes/flow-premium-iea.csv` and `notes/hormuz-iea-flows.csv`.

The runs for this page are all on `amd_student`:
- jobs 1972484 (`MEMBERS=global_tcn`) and 1972485 (20 seeds), 2026-10-24;
- jobs 1972767 (v3 folds), 1972768 (replays) and 1972803 (v3 report), 2026-10-25;
- the margin layer: 1972719 (`margins.py` folds and replay), 1972755 (`fold J margins`), 1972756 and, after the copula merge, 1972934 (the 3-member replay with `CHAIN_MARGINS=1`) and 1972757 (the `margins.py` replay with the premium curve), 2026-10-24/25;
- the supply-disruption test: 1973498 (Bayesian folds), 1973499 (network folds) and 1973500 (replay), and the cost-only variant 1973890 (folds) and 1973891 (replay), 2026-10-25;
- the gas channel 1974005 (folds), and the replays on the IEA curve 1974021 (3m), 1974022 (3m with margins), 1974023 (all members), 1974024 (4x) and 1974025 (3m with gas), 2026-10-25.

**Files to copy up as well:**
- `notes/industry/fred_series.csv`: `macro_data.py` reads the industry series list from it.
- `notes/flow-premium.csv`, for the scenario premium.
- `data/raw/macro/`, with the context series and, for the margin layer, the EIA spot workbook (`eia_PET_PRI_SPT_S1_D.xls`).

**The v3 report runs on Iridis too.** Its results come to 817 MB, so rather than download them, copy `runs/macro/fold-*.json` up and run `CHAIN_TAG=v3 sbatch --nodes=1 --partition=amd_student --mem=24G --wrap ".venv-nn/bin/python -u experiments/macro_chain.py report"`; it takes about 2 minutes.

If `loginx001` drops a transfer, use `loginx002`; its banner recommends that node for jobs that need no GPU.
