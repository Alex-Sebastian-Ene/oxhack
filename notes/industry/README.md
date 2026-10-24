# Industry impact: research for the price → business costs part of the chain

Research from 24 Oct 2026 by Eileen. Nothing here is decided; move what we pick into
`docs/design.md`. Every number carries its source and the date we collected it; anything we could
not open at the source is marked low confidence.

## What this part does

The flow lane turns a change in Hormuz flow into a change in Brent. This part takes that Brent
change and answers, for a chosen industry: which of its costs move, by how much, how fast, and
what a procurement or supply-chain manager should do about it.

```
flow lane: ships → flow → Brent      this part: Brent → fuel → freight → materials → inflation → actions
```

The user is a procurement or supply-chain manager at a mid-size company in a fuel- or
petrochemical-heavy industry (logistics, retail importers, manufacturing, food, airlines). They
make cost decisions every month and have no in-house economist.

**Handoff we need from the flow lane:** a Brent path, e.g. `brent_usd_per_bbl` by date, for the
current estimate and for each what-if scenario.

## Files

| File | What it holds | Columns |
|---|---|---|
| `pass_through.csv` | How each cost channel responds to oil, and how fast | `channel, effect, per, lag_from_days, lag_to_days, measure, region, source, source_url, source_date, collected_at, confidence` |
| `industry_exposure.csv` | Default oil-linked cost share per industry | `industry, oil_linked_cost, share_pct, measure, year, region, source, source_url, source_date, collected_at` |
| `fred_series.csv` | FRED series to fit the pass-through on; each ID checked on its FRED page | `fred_id, name, layer, frequency, checked_on` |

## Findings the model should reproduce

- **Size:** a 10% oil move shifts energy CPI by ~2.3% within two quarters, food by ~0.3% and core
  by ~0.1% over ~8 quarters; headline ~0.4% in total ([Fed FEDS Note, Dec 2023](https://federalreserve.gov/econres/notes/feds-notes/second-round-effects-of-oil-prices-on-inflation-in-the-advanced-foreign-economies-20231215.html)).
- **Speed:** fuel moves in days, freight in weeks (surcharges trail diesel by 1–2 weeks, some reset
  monthly or quarterly), plastics over ~10 months, food and core over ~2 years. See
  `pass_through.csv`.
- **Falls are slower than rises ("rockets and feathers"):** retail diesel cuts take 3–6 working days
  against 0–3 for rises, but are fully passed on by 3 weeks ([prix-carburant.eu, Oct 2026](https://prix-carburant.eu/en/article/rockets-and-feathers-fuel-price-cuts-passed-on-slower-than-rises)).
  Further down the chain the lag is longer: PET resin fell 2.5% when Brent fell 8.5% in Aug 2026
  ([WKAI](https://wkaiglobal.com/blogs/crude-oil-prices-retreat-while-cost-pass-through-across-the-polyester-chain-remains-limited)).
  Use separate, slower coefficients for falls.
- **The cause decides the sign:** a supply-driven fall (Hormuz reopening) lowers costs while sales
  hold; a demand-driven fall (2008, 2020) lowers costs and sales together
  ([Kilian 2009 replication](https://arxiv.org/html/2409.00769v2)). Show which case a scenario is.
- **Most exposed:** airlines (fuel 31.4% of costs, 2026), container shipping (~25%), trucking (~21%),
  then farming, cement and chemicals. See `industry_exposure.csv`; the shares use different
  measures, so rebuild one consistent measure from an input-output table before comparing.
- **Train on 2000 onward.** Oil predicted US core inflation before 1981 but not after
  ([FRBSF 2005-28](https://www.frbsf.org/research-and-insights/publications/economic-letter/oil-price-shocks-and-inflation)),
  so older data overstates today's effect. Backtest on 2014–16 and 2022–23.

## How to get one consistent cost share per industry

Take each industry's direct-requirements share spent on petroleum products, transport services,
chemicals and plastics from an input-output table: [BEA](https://www.bea.gov/industry/input-output-accounts-data)
(US, free API key), [ONS](https://WWW.ons.gov.uk/economy/nationalaccounts/supplyandusetables/datasets/ukinputoutputanalyticaltablesdetailed)
(UK, latest 2020; ONS suggests 2019 as more typical) or [OECD ICIO](https://www.oecd.org/en/blogs/2025/11/oecd-inter-country-input-output-icio-tables-and-trade-in-value-added-tiva-database-launch-of-the-2025-edition.html)
(multi-country, to 2022). Industry cost impact ≈ Σ (share of input × modelled price change of
that input). Rescale shares to current prices: airline fuel went from 25.4% to 31.4% of costs in
one year because of price alone.

## Actions the product can recommend when oil falls

1. Audit fuel surcharges: move monthly or quarterly resets to weekly; check base price and mpg
   ([FreightWaves](https://www.freightwaves.com/checkpoint/fuel-surcharge-in-trucking/)).
2. Contract vs spot: spot freight follows fuel within about a week, so wait before locking annual
   contracts, or add a fuel index clause.
3. Time materials purchases: plastics and packaging lag crude by months.
4. Check suppliers: compare what each charges with what the model says their costs did.
5. Pricing and margin: pass savings on or keep them.
6. Hedging: how much of next year's fuel to lock in at the lower price.

## Weak spots

- Industry averages hide companies: a hedged large fleet and an owner-operator on retail diesel
  are both "trucking". Let users override shares; show ranges, not points.
- Contracts and hedges change when a fall arrives (airlines hedged about a third of 2026 fuel,
  per IATA as reported by S&P Global; not opened at source).
- Second-round effects are small and slow; widen the range beyond six months.
- Monthly data since 2000 gives ~300 points and few big falls: keep the model simple.

## Open questions

- [ ] US data (fastest, all on FRED) or UK framing (ONS, fits OxHack)?
- [ ] Five curated industries for the demo, or all from the BEA summary table?
- [ ] Who owns flow → Brent (the step before this part)? Ed's `docs/ideas.md` (on branch `claude/trusting-turing-r78njk`) sketches it.
