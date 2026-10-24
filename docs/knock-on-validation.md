# Knock-on chain: which links hold up

Technical companion to section 4 of [design.md](design.md) ("each link cited"). The script is
[experiments/oil_chain.py](../experiments/oil_chain.py); its full output, with fetch dates and
date ranges for every series, is [notes/oil-chain-links.md](../notes/oil-chain-links.md).

## Method

- **Data:** ten US series from FRED (St. Louis Fed), averaged to months: Brent spot (EIA), retail
  petrol (EIA), CPI energy, CPI all items and CPI less food and energy (BLS), 5-year breakeven
  inflation, effective fed funds, unemployment (BLS), the 30-year fixed mortgage rate (Freddie
  Mac) and the 10-year Treasury yield. Downloads are cached in `data/raw/` (git-ignored).
- **One regression per link:** the monthly change of the downstream series on the current and
  lagged monthly change of the upstream one. Prices use log changes, rates use level changes.
  Lags: 0–2 months for petrol and energy CPI, 0–12 for headline and core CPI, 0–1 for
  expectations and mortgages. The effect is the sum of the lag coefficients.
- **Errors:** Newey–West (lag 6 or 12), quoted as ± one standard error.
- **Validation:** each link is fitted on 1991–2008 and used unchanged on 2009–2026 (2003–2013 and
  2014–2026 for breakevens, which start in 2003). An out-of-sample R² above 0 means the link
  predicts better than a constant in years it never saw. A refit on the test years alone shows
  whether the size has drifted.
- **Fed step:** a Taylor-style regression of the fed funds level on last month's 12-month core
  inflation and unemployment, restricted to months with fed funds above 0.5% (outside the zero
  lower bound), in two eras.

## Results (FRED data fetched 2026-10-24)

| Link | Effect, fitted 1991–2008 | Out-of-sample R², 2009–2026 | Refit on 2009–2026 | Verdict |
|---|---|---|---|---|
| Oil → petrol | +6.9% ± 0.8 per 10% oil rise, within 2 months | +0.52 | +5.2% ± 0.8 | **Solid**, slightly weaker lately |
| Oil → energy CPI | +3.2% ± 0.5 | +0.48 | +2.5% ± 0.3 | **Solid** |
| Oil → headline CPI | +0.36 pp ± 0.08 of the price level within 12 months | +0.40 | +0.41 pp ± 0.12 | **Solid and stable** |
| Oil → core CPI | −0.01 pp ± 0.03 | −0.12 | +0.19 pp ± 0.10 | **Not in the old data**; some pass-through since 2009 |
| Oil → 5y inflation expectations | +0.17 pp ± 0.05 (2003–2013) | +0.02 | +0.08 pp ± 0.01 | **Weak**, halved since 2014 |
| Core inflation → fed funds (Taylor) | +1.85 ± 0.20 per pp (1991–2008) | not tested | +0.66 ± 0.30 (2016–2026) | **Unstable** across eras |
| 10y yield → mortgage rate | +0.89 ± 0.05 per pp | +0.71 | +0.95 ± 0.10 | **Solid** |
| Fed funds → mortgage rate, holding the 10y | −0.02 ± 0.04 per pp | (same regression) | −0.02 ± 0.10 | **None directly** |

Chained for a 10% oil rise with the 1991–2008 links:
- petrol +6.9%, energy CPI +3.2%, headline CPI +0.36 pp;
- core CPI about 0, so the Taylor-rule Fed response is −1 bp ± 5;
- the mortgage effect through fed funds is about 0.

## Fold-level split testing (k = 8 to 16)

A single split depends on where the cut falls. `uv run experiments/oil_chain.py cv` cuts each
link's whole window (1991–2026; 2003–2026 for breakevens) into k contiguous blocks, for every k
from 8 to 16: 108 folds per link.
- **Blocked:** each block is held out once, and the link is fitted on the rest, with a gap the
  length of the lags either side of the block.
- **Forward:** each block is predicted from earlier blocks only, as a time-honest check.

Full output: [notes/oil-chain-cv.md](../notes/oil-chain-cv.md).

| Link | Single split R² | Blocked pooled R², k = 8–16 | Forward pooled R² | Folds with R² > 0 | Fold effects, median [5%, 95%] | Verdict |
|---|---|---|---|---|---|---|
| Oil → petrol | +0.52 | +0.53 to +0.54 | +0.52 to +0.54 | 92% | +5.8% [+5.4, +6.5] | **Holds at every k** |
| Oil → energy CPI | +0.48 | +0.48 to +0.50 | +0.47 to +0.49 | 90% | +2.8% [+2.5, +3.0] | **Holds at every k** |
| Oil → headline CPI | +0.40 | +0.36 to +0.37 | +0.31 to +0.34 | 74% | +0.40 pp [+0.31, +0.43] | **Holds on average**; calm years add little |
| Oil → core CPI | −0.12 | −0.14 to −0.12 | −0.20 to −0.13 | 16% | +0.12 pp [−0.00, +0.13] | **Fails at every k** |
| Oil → 5y inflation expectations | +0.02 | +0.20 to +0.21 | +0.17 to +0.24 | 91% | +0.11 pp [+0.09, +0.13] | **Holds at every k**; the single split understated it |
| 10y yield → mortgage rate | +0.71 | +0.76 | +0.72 to +0.75 | 97% | +0.92 [+0.87, +0.95] | **Holds at every k** |
| Fed funds → mortgage, holding the 10y | (same regression) | (same regression) | | | −0.02 [−0.04, +0.01] | **No effect**; the range straddles 0 |

The Taylor-rule coefficient on core inflation has a median of 0.50–0.57 across k, but it ranges
from **0.23 to 1.77** depending on which block is held out: the Fed link is unstable at every k.

**What it changes:**
- The conclusions don't depend on the cut: every link's R² is flat from k = 8 to k = 16, and the
  blocked and forward versions agree.
- The one link the single split got wrong is **oil → inflation expectations**. Its 2003–2013
  training window held the 2008 crash, which made the 2014–2026 test look like a failure
  (R² 0.02). Across 108 folds it predicts consistently (R² 0.20), with a stable effect of about
  +0.11 pp per 10% oil rise. So the mortgage route, oil → expectations → 10-year yield → mortgage,
  is weak in size but real.
- **For the industry series (splits B and C):** the same `cv_link()` runs on any series with the
  same arguments as `link()`, so splits B and C can be checked the same way. With 2004–2026 data,
  k = 8 to 16 gives blocks of 17–33 months.

## What this means for the product

1. **The trustworthy part of the chain is oil → petrol → energy → headline CPI.** These links are
   large, precisely estimated, and predict 2009–2026 out of sample with R² 0.40–0.52. The "what
   if" slider can show them with a ± band.
2. **Oil → Fed rate is the weakest link, not the strongest.** The Fed reacts to core inflation,
   oil barely moved core inflation before 2009, and the size of the Fed's reaction itself changed
   between eras. The demo should show the Fed step as a scenario range, or as "the Fed usually
   looks through oil shocks", rather than as a point forecast. This inverts the fallback order
   in design section 7, "oil price → CPI → Fed rate first".
3. **Mortgages follow long yields, not the policy rate.** For a cost-of-living card, the route is
   oil → inflation expectations → 10-year yield → mortgage. The expectations step is small (about
   +0.11 pp per 10% oil rise) but holds across all 108 folds, so the honest mortgage effect of an
   oil shock is real but small.
4. **Flow → oil price is not tested here.** We have no historical flow series yet. The link
   needs a supply-shock event study (dates and barrels from a cited source; ask the research
   desk), and the oil-price layer in [oil-price-model.md](oil-price-model.md) supplies the
   distribution of price moves around it.

## Limits

These are average historical pass-throughs: they mix demand-driven and supply-driven oil moves
and are not causal effects of a supply shock. Everything is US; a UK version would swap in ONS
CPI and the Bank Rate. The Fed regression uses levels, which are persistent, so treat its
coefficients as descriptive.
