# Oil-price model: non-Gaussian Lévy processes with a volatility state

Technical notes for the oil-price layer of the knock-on chain in [design.md](design.md). The
model gives the **distribution** of Brent moves over 1, 5 and 21 trading days. The what-if slider
and tail-risk numbers need that distribution; no model here predicts the direction of the price.

Code: [experiments/non_gaussian.py](../experiments/non_gaussian.py) (eight Lévy processes compared),
[experiments/levy_fourier.py](../experiments/levy_fourier.py) (volatility state plus learned
Lévy measure). Generated results: [notes/non-gaussian-results.md](../notes/non-gaussian-results.md)
and [notes/levy-fourier-results.md](../notes/levy-fourier-results.md). Cluster runs:
[iridis.md](iridis.md). How the price links to petrol, CPI, the Fed and mortgages:
[knock-on-validation.md](knock-on-validation.md).

## Data

- **Series:** Brent spot, FRED series `DCOILBRENTEU` (source EIA), daily from 1987-05-20, fetched
  2026-10-24, cached in `data/raw/` (git-ignored).
- **Returns:** daily log returns between consecutive available prices: 9,111 returns, 168 of them
  exactly zero. Zero-return days are kept everywhere. Many are stale quotes, so the models that
  could otherwise put a point mass on 0 are restricted (see "Fixes").
- **Split:** train before 2008-10-15, test 2008-10-15 to 2026-10-20 (4,556 days). Rolling refits
  train on all years before Y and score year Y, for 1998–2026.
- **Spring 2020:** Mar–May 2020 (WTI went negative; Brent fell 64% on 2020-04-21) is reported
  separately, because that one day moves the Gaussian's mean daily score by about 0.07.
- **WTI:** WTI front-month futures (EIA `RCLC1`) settled at −$37.63 on 2020-04-20, so log returns
  of contract 1 break. Use contract 2, or drop that week.

## Models

### Lévy processes

A Lévy process X_t has independent, stationary increments. It is described completely by its
characteristic exponent ψ, where E[exp(iuX_t)] = exp(t ψ(u)). By the Lévy–Khintchine formula:

    ψ(u) = iγu − σ²u²/2 + ∫ (e^{iux} − 1 − iux·1{|x|<1}) ν(dx)

The quadratic −σ²u²/2 is Brownian motion. The Lévy measure ν says how often jumps of each size
occur, and it sets the tails. The time unit is one trading day: holidays are dropped, and weekend
returns have variance only 1.13 times that of single days, so a trading-day clock fits.

| Model | ψ(u) (location term iμu omitted) | Reference parameterisation |
|---|---|---|
| Gaussian | −σ²u²/2 | Brownian motion |
| Student-t | log of Bessel-K form: (ν/2) log z + log K_{ν/2}(z) − log Γ(ν/2) − (ν/2−1) log 2, z = √ν·s·\|u\| | Hurst (1995) |
| NIG | δ(√(α²−β²) − √(α²−(β+iu)²)) | Barndorff-Nielsen (1997) |
| Variance gamma | −(1/ν) log(1 − iθνu + σ²νu²/2) | Madan, Carr and Chang (1998) |
| Merton | −σ²u²/2 + λ(exp(iμ_J u − σ_J²u²/2) − 1) | Merton (1976) |
| Kou | −σ²u²/2 + λ(p η₊/(η₊−iu) + (1−p) η₋/(η₋+iu) − 1) | Kou (2002) |
| CGMY | C Γ(−Y)[(M−iu)^Y − M^Y + (G+iu)^Y − G^Y] | Carr, Geman, Madan and Yor (2002) |
| α-stable | −\|cu\|^α (1 − iβ sign(u) tan(πα/2)) | Nolan S1 |

### From exponent to density: the COS method

The h-day law has exponent hψ. Its density on [a, b] is recovered as a Fourier-cosine series
(Fang and Oosterlee, 2008):

    f(x) ≈ Σ'_k A_k cos(u_k (x − a)),  u_k = kπ/(b − a),  A_k = 2/(b − a) · Re{exp(hψ(u_k) − i u_k a)}

The prime halves the k = 0 term. The CDF is the integrated series. The range is ±3 for daily
returns (wide enough for the −0.644 day), ±4 at 5 days and ±5 at 21 days, with 4,096 or 2,048
terms.

Closed forms are used instead where the series struggles:
- **Gaussian and Merton:** their thin tails would be clipped.
- **Variance gamma:** its characteristic function decays only like a power of u, so the series
  rings in the far tails.

Densities below 1e-12 are clipped and counted in every table.

### Volatility state

- **EWMA** (in `non_gaussian.py`): σ²_t = 0.94 σ²_{t−1} + 0.06 r²_{t−1}, seeded on the first 50
  days, which are then left out of fitting and scoring.
- **GARCH(1,1)** (in `levy_fourier.py`): σ²_t = ω + α(r_{t−1} − μ)² + β σ²_{t−1}, started at the
  model's unconditional variance and fitted jointly with the innovation.

In both, returns are r_t = μ + σ_t X_t, with X_t a unit-variance Lévy increment. The `iid`
family holds σ constant.

### Learned Lévy measure (Fourier-CGMY)

The innovation is a pure-jump Lévy process whose Lévy density is CGMY times a learned factor:

    ν(x) = C |x|^(−1−Y) exp(−M x + g₊(x)),    x > 0
    ν(x) = C |x|^(−1−Y) exp(−G |x| + g₋(|x|)), x < 0
    g(s) = Σ_{k=1..6} a_k sin(πs/L) sin(πks/L)  for s ≤ L = 15 sd, and 0 beyond

- **Properties:**
  - ν ≥ 0 for every parameter value, so every fit is a valid Lévy process, and multi-day laws
    stay coherent.
  - With every a_k = 0 the model is exactly CGMY.
  - Each basis term behaves like s² at 0 and like (L − s)² at L. The even terms are not
    symmetric about L/2, so small and large jumps can be reshaped independently.
  - C is set so that Var X = 1.
- **Exponent:** ψ = ψ_CGMY (minus its mean) + ∫ (e^{iux} − 1 − iux) ν_CGMY(x) (e^{g(x)} − 1) dx.
  The integral is one FFT on a 2¹⁷-point grid whose frequencies are the COS frequencies. The
  density then comes from the COS series by one DCT-I on [−40, 40] sd.
- **Prior:** independent Gaussian priors a_k ~ N(0, (τ/k)²), so the fit is a ridge-penalised MAP
  estimate.
- **Choosing τ:** τ ∈ {0.25, 0.5, 1, 2} is picked by the log score on the last 4 training years,
  with τ = 0 (plain CGMY) scored alongside.
- **Uncertainty:** a Laplace approximation (Hessian at the MAP) gives 90% bands for g₊ and g₋.
- **Fitting:** L-BFGS-B, then a Nelder–Mead polish.

### Scoring

- **Daily log score:** the mean log density of each realised test return, in nats per day; higher
  is better.
- **Tail coverage:** the % of test days below the model's 1% and 5% quantiles and above its 95%
  and 99% quantiles. A calibrated model shows 1 / 5 / 5 / 1. The binomial standard error over
  4,556 days is 0.15 at 1%.
- **h-day scores:**
  - `non_gaussian.py` uses exp(hψ) on every overlapping 5- and 21-day window.
  - `levy_fourier.py` simulates 20,000 GARCH paths from every test day and scores them by CRPS.
    It uses the same random numbers for every model, so their differences are precise.
- **Uncertainty:** every difference has a Newey–West standard error (lag 10 daily, lag h for h-day
  windows), i.e. a Diebold–Mariano test.

## Verification

- **Self-checks:** `uv run experiments/levy_fourier.py check` runs these:
  - the exponent against direct Lévy–Khintchine quadrature (relative error 2e-9);
  - the density's mass, mean and variance (1, 0, 1 to 1e-6);
  - the sampler (KS 0.006), the GARCH filter and CRPS against brute force;
  - the off-grid density decay, and that a collapsed fit loses.

  They run first in every Iridis job.
- **Link checks on the real results:** `experiments/validate_links.py` writes
  [notes/link-checks.md](../notes/link-checks.md); 10 of 11 checks pass.
  - Gaussian, Student-t and CGMY give the same test score in both scripts (to 2e-5).
  - The simulator matches the Gaussian closed-form CRPS (to 1e-5).
  - Laptop and Iridis agree (to 1e-7).
  - The fixed split and the 2009 refit give the same GARCH parameters (to 2%).
  - The failing check is the Fourier-CGMY reproducibility described under "Learned tail".
- **Tests:** `tests/` holds 37 tests. They cover the Linear bus, all three scripts, and the links
  between the two Lévy scripts:
  - the same CGMY process in both scripts;
  - NIG closed under exp(hψ);
  - Student-t exp(5ψ) against simulated sums;
  - the path simulator against Gaussian closed forms;
  - Fourier-CGMY with a = 0 equal to CGMY;
  - recovery of GARCH and Student-t parameters from simulated data.
- **Independent replication:** a separate session rewrote the Gaussian / Student-t / NIG
  comparison from the spec alone.
  - It matched `notes/non-gaussian-results.md` to 1e-4 nats/day, with the same parameters and tail
    coverage.
  - It added Diebold–Mariano tests, a reversed split and a 1998–2026 rolling refit.
  - It found that volatility scaling beats i.i.d. in every set-up (z ≈ 7), and heavy tails beat
    the Gaussian (z ≈ 2.4, and z ≈ 11 once the 20 most extreme days are removed).
  - The order among heavy-tailed models was not significant.
- **Second dataset:** a re-run on WTI futures (EIA contracts 1 and 2, to 2024-04-05, where the EIA
  file currently ends) reproduced the conclusions:
  - EWMA scaling gives 85–90% of the gain;
  - the model ranking is near-identical;
  - WTI's lower tail is a little heavier than any model allows after 2008.

## Results

### Which Lévy process (`non_gaussian.py`, test 2008-10-15 to 2026-10-20)

| Comparison | nats/day | Without Mar–May 2020 |
|---|---|---|
| Student-t vs Gaussian, i.i.d. | +0.243 ± 0.103 | +0.090 ± 0.009 |
| EWMA-scaled Gaussian vs i.i.d. Gaussian | +0.303 ± 0.109 | |
| Heavy tails on top of EWMA (Student-t+EWMA vs Gaussian+EWMA) | +0.029 ± 0.007 | +0.022 ± 0.006 |

- **i.i.d. models:** Student-t, CGMY and NIG are within their errors of each other. VG, Merton,
  Kou and α-stable are about 2 standard errors worse than Student-t.
- **After EWMA scaling:** all seven heavy-tailed models are within 0.0033 nats/day of each other,
  and only α-stable is measurably worse.
- **α-stable's time scaling is wrong:** its 21-day tail coverage is 0.55 / 3.28 / 2.27 / 0.49 %,
  and without spring 2020 it scores below the Gaussian at 21 days.

**Conclusion:** most of what looks like fat tails in raw returns is volatility that changes over
time. The rest is real but small, and on daily data any of Student-t, NIG or CGMY captures it.

### Learned tail (`levy_fourier.py`, Iridis)

Iridis jobs 1971111 (GARCH) and 1971112 (i.i.d.): 60 runs, and the fit-health line is clean
(largest daily log density 3.88). Differences are in nats/day, ± one Newey–West standard error.

| Comparison | Fixed split | Rolling 1998–2026, pooled | Rolling without 2020 |
|---|---|---|---|
| Learned tail − CGMY, with GARCH | −0.0000 ± 0.0000 | −0.0001 ± 0.0001 | −0.0000 ± 0.0001 |
| Learned tail − CGMY, i.i.d. | +0.0005 ± 0.0004 | +0.0012 ± 0.0007 | +0.0002 ± 0.0003 |
| GARCH − i.i.d. (both CGMY) | **+0.0946 ± 0.0126** | **+0.0778 ± 0.0099** | |
| GARCH-CGMY − GARCH-Student-t | +0.0006 ± 0.0004 | +0.0005 ± 0.0005 | |
| GARCH-Student-t − GARCH-Gaussian | **+0.0285 ± 0.0069** | **+0.0295 ± 0.0060** | |

- **τ selection:** the chosen τ varies from year to year, but validation scores across τ differ by
  at most 0.0004 nats/day.
- **Bands:** the Laplace 90% bands for g contain 0 at every jump size from 0.5 to 12 sd, on both
  sides, with and without GARCH.
- **Multi-day forecasts:** at 5 and 21 days no innovation beats GARCH-Student-t by more than its
  error (21-day CRPS × 100: CGMY −0.012 ± 0.010).
- **Calibration:** GARCH-CGMY tail coverage is 0.92 / 5.27 / 4.32 / 0.70 %. The upper tail is
  slightly too wide, because oil rallies are less extreme than its crashes.
- **Reproducibility:** re-running 2003 on a laptop reproduces the Gaussian, Student-t and CGMY
  fits to 1e-7 in daily log score. The Fourier coefficients differ by up to 3.4× their size, with
  daily scores within 1.2e-3 (mean 1e-5). The likelihood is flat in the Fourier directions, so
  tiny numerical differences land on different, equally good coefficients. That is the
  non-identifiability behind the null result, and [notes/link-checks.md](../notes/link-checks.md)
  reports it as the one failing check.
- **Earlier basis:** a run with the mirrored basis (fix 5 below) reached the same conclusion. Its
  apparent i.i.d. down-tail signal, a band excluding 0 from 2 to 12 sd, disappeared with the
  corrected basis, so it was an artefact of the mirror.

**Conclusion:** use GARCH(1,1) with CGMY or Student-t innovations. On daily Brent, a learned Lévy
measure isn't justified even without the volatility state. The volatility state is worth about
80 times more than any change to the tail shape.

### Rejected earlier: a Fourier series for the price itself

A Fourier series in *time* or in the *price level*, used as the drift (instead of the x² of an
Ornstein–Uhlenbeck potential), does not survive:
- **Seasonality:** annual harmonics in the drift are not significant (p = 0.11). The volatility
  seasonality doesn't repeat between halves of the sample (correlation 0.02).
- **Fourier fit to the log price:** it forecasts far worse than a random walk (log-price RMSE 0.55
  vs 0.15 at 21 days, 0.73 vs 0.39 at 252 days).
- **Fourier potential in the price level:** it doesn't beat OU (p = 0.08–0.36). OU itself is
  marginal (p = 0.12, half-life 5.3 years), with only 35 crossings of the median price in 39
  years.

The Fourier idea is therefore applied to the jump measure, where it keeps the process valid.

## Fixes made because validation caught them

1. **Range too tight:** the daily COS range was ±1, which wrapped tail mass around on 2020-04-21
   (log error up to 0.17). It is now ±3.
2. **Likelihoods that could run off to infinity on zero-return days:**
   - Merton with σ → 0, and Kou weakly, can form a point mass. They now have a diffusion floor of
     σ ≥ 0.1 sd and three starting points.
   - Variance gamma has a density pole when ν > 2 days, so ν is capped at 2.
3. **h-day results depended on the window start day** (Student-t's 21-day advantage ranged from
   +0.02 to +0.44 over start days). They now use every overlapping window, with lag-h errors.
4. **Off-grid density clamping:** `np.interp` returned the edge value beyond ±40 sd. A 2022 CGMY
   fit exploited it by sending σ → 0 and scoring +340 nats/day. The log density now falls 50 nats
   per sd beyond the grid. A self-check covers it, and the report's "Fit health" line flags any
   daily log density above 8.
5. **Mirrored basis:** the first Fourier basis, 1 − cos(2πks/L), is symmetric about L/2, which
   forced the learned shape at 12 sd to equal that at 3 sd. It was replaced by
   sin(πs/L) sin(πks/L).

## Limits and next steps

- **Daily data:** about 17 days beyond 4 sd in 21 training years (after volatility scaling) is too
  few to learn a tail shape. Tick data would help:
  - Dukascopy Brent CFD ticks from 2011 and WTI from 2013 (free, but its terms likely forbid
    putting the data in this public repo);
  - CME futures via Databento (paid).
- **GARCH:** it is a deterministic filter. The fully Bayesian version (a latent volatility state
  driven by a Lévy process, filtered with particle methods) is the Godsill-style state-space model
  the original idea pointed at.
- **Direction:** nothing here predicts which way the price moves; point forecasts are about "same
  as today".

## Reproduce

```bash
uv run experiments/non_gaussian.py                      # about 4 min; writes notes/non-gaussian-results.md
uv run experiments/levy_fourier.py check                # self-checks
uv run experiments/levy_fourier.py fit                  # fixed split, GARCH (runs/levy/fixed.json)
uv run experiments/levy_fourier.py fit --family iid     # fixed split, constant sigma
uv run experiments/levy_fourier.py report               # notes/levy-fourier-results.md
uv run experiments/oil_chain.py                         # knock-on links, notes/oil-chain-links.md
uv run --no-project --with pytest --with numpy --with scipy --with pandas pytest -q tests
```
