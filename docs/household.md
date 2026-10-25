# Household cost of living over time

The people side of the chain in [chain.md](chain.md): what households pay, what they earn, and the
gap between them, for the US, UK and euro area, monthly from 2000. It sits next to the basket-item
price model ([cost-of-living.md](cost-of-living.md)). That model forecasts
item prices; this page measures how households have actually fared, and what the Hormuz scenarios
would do to their pay.

| Code | What it does | Output |
|---|---|---|
| `experiments/household.py fetch` | Downloads and caches every series (`data/raw/macro/`, git-ignored) | |
| `experiments/household.py report` | Builds the panel, the measures, the UK household-group tables and the scenario table | `notes/household-costs.md`, `notes/household-panel.csv`, `notes/household-measures.csv`, `notes/household-groups.csv`, `notes/household-group-weights.csv`, `notes/household-scenarios.csv`, `notes/household-group-scenarios.csv` |
| `experiments/household_dash.py` | Cuts the notes above into the dashboard's ten files, with a table of every series' source, code, period and fetch date, and wraps the page `experiments/household_dash.html` | `runs/dash/*.csv`, `runs/dash/page.json` (git-ignored) |
| `tests/test_household.py` | Mortgage arithmetic, real pay and work-minutes, squeezes, the HCI parser, the scenarios, and a check of the cached ONS file against its bulletin | |

## Data

48 series plus the ONS Household Costs Indices. Every row of `notes/household-panel.csv` carries
its source, code, unit, frequency and fetch date.

| What | US | UK | Euro area |
|---|---|---|---|
| Prices | CPI and essentials: food at home, household energy, electricity, gas, gasoline, rent, shelter (BLS via FRED, SA) | CPI, CPIH, food, electricity, gas and other fuels (and each), fuels and lubricants, housing, water and fuels (ONS MM23) | HICP and food, household energy (and each), fuels, actual rentals (Eurostat via FRED) |
| Money prices | BLS US city average prices: petrol, electricity per kWh, gas per therm, eggs, milk, bread, beef, chicken, coffee, bananas | – | – |
| Pay | Average hourly earnings, production and nonsupervisory employees (AHETPI; all employees from 2006) | Average weekly earnings, total pay (KAB9) | Labour cost index, wages and salaries (quarterly, EA20, from 2009) |
| Housing | 30-year mortgage rate (Freddie Mac), median sales price (quarterly) | 2-, 3- and 5-year fixed (75% LTV) and revert-to rates (Bank of England); UK HPI average price (Land Registry) | – |
| Buffers and mood | Real disposable income per head, saving rate, debt service, Michigan sentiment, median household income (annual) | – | Consumer confidence (EA21) |
| Household groups | – | ONS Household Costs Indices by income decile, tenure, retirement and children: indices, official 12-month rates and spending weights, 2005 to June 2026 | – |

- **Checks on the inputs:**
  - Each ONS series is fetched with its official title and dropped if the title doesn't match the expected item, so a wrong series code fails loudly.
  - The Bank of England codes were checked against the Bank's own series titles.
  - The parsed Household Costs Indices reproduce every 12-month rate quoted in the ONS bulletin (all households, deciles 2 and 9, the four tenures, retired and non-retired, with and without children); `tests/test_household.py` checks this.
- **Frequency:** quarterly and annual series are carried forward over the months they cover. Euro-area real pay is computed per quarter, against the quarter's average HICP.
- **Euro-area composition:** EA21 is the euro area with Bulgaria (from January 2026), back-cast by Eurostat, used for confidence. EA20 is used for the labour cost index.

## Measures

| Measure | Definition |
|---|---|
| Real pay | Pay ÷ CPI, index (2019 = 100), and its 12-month change |
| Essentials in units of pay | Each essential's price index ÷ pay (2019 = 100): above 100, it takes more work to buy than in 2019 |
| Work-minutes (US) | 60 × price ÷ hourly pay: minutes of work for a gallon of petrol, 100 kWh, 10 therms, a dozen eggs and so on, plus a fixed weekly shop of our own choosing (labelled) |
| Mortgage burden | Monthly repayment per 100,000 borrowed, as a share of a full-time month of average pay (US 30-year; UK 2-year fixed over 25 years). Typical home: US, 80% of the median price against median household income; UK, 75% of the UK HPI average price against one average earner |
| Squeezes | From a peak in real pay to its lowest point before the peak was regained, if the fall lasts 6 months or more: depth, length and the month of recovery |
| UK household groups | HCI 12-month rates by group at key dates (`notes/household-groups.csv`: index and official rate for 11 key categories; weights for all 25 in `notes/household-group-weights.csv`), the rise since 2021-01, spending shares, and the approximate first-round cost of the 2026 energy and fuel moves (share × the group's own category index change) |
| Hormuz scenarios | Real pay over 3, 6 and 12 months from 2026-02 under the knock-on chain's flow scenarios: each loss held for 12 months (`notes/chain-scenarios-3m.csv`) and 2026 as the IEA counts it month by month (`notes/chain-scenarios-2026-3m.csv`; column `scenario` in `notes/household-scenarios.csv`). Nominal pay keeps its pace of the 12 months before the origin, so the band is the CPI band. Set against what happened |

## What it shows (see `notes/household-costs.md` for every table)

- **Real pay's 2021–24 low against 2019:**
  - US 101.5 (2022-06), now 105.4;
  - UK 99.6 (2022-10), now 105.7;
  - euro area 95.9 (2023-06), now 99.8, **still below 2019**.
- **The UK's long squeeze:** real weekly pay fell 11.8% from 2008-02 to 2014-03 and was not back at its peak until 2021-05.
- **Who paid for 2022 in the UK:**
  - The lowest-income tenth faced 14.5% household-cost inflation in the year to 2022-10, against 11.3% for the highest. Energy and food are a larger share of their budgets: energy 6.0% against 3.0% of spending in the 2026 weights.
  - In 2024 the richest caught up through mortgage interest (4.0% against 1.7% in the year to 2024-06).
  - From 2021-01 to 2026-06 both rose about 37%.
- **Essentials:**
  - UK household energy cost 1.8 times as much work as in 2019 at its 2022 peak, and is still 16% above 2019.
  - A gallon of US petrol took 6.7 minutes of work in 2019, 11.0 at the 2022 peak and 8.2 in 2026-09.
- **Mortgages:** a UK 2-year fixed repayment per £100,000 rose from 15.8% of an average month's pay in 2021 to 21.1% in 2023.
- **2026:**
  - From February 2026, motor fuel rose 25–31% in all three regions. Real pay fell 0.9% in the US (to September), 1.0% in the UK (to August) and 0.3% in the euro area (first to second quarter).
  - Given the chain's CPI paths for 2026 as the IEA counts it (89 points of strait flow lost in March to 47 in September), real pay was forecast at −0.7% (US) and −0.5% (UK) after 3 months, and −0.3% and −0.2% after 6. The actuals were −1.1% and −1.0%, then −0.5% and −1.0%, inside the bands. (Before the chain switched to the IEA's count, the table held 82 points as "2026".)

## A Hormuz closure by UK household group (`notes/household-group-scenarios.csv`)

**Method:**
- Take the item price fans of the basket-item model: `notes/cost-of-living-fans.csv` ([cost-of-living.md](cost-of-living.md)), generated 2026-10-25 from the converged fits listed in `notes/cost-of-living.md` (Iridis jobs 1973278–1973324). The fans run from 2026-02 under no closure and 25%, 50% and 100% closures, plus the outlook from 2026-09.
- Weight them by each group's 2026 HCI spending shares:
  - food goes to the food items, split by their CPI weights;
  - electricity, gas and other fuels to electricity and gas;
  - motor fuels to fuel;
  - restaurants and hotels to restaurants;
  - mortgage interest is held flat, because the price model has no rates;
  - the rest goes to its "rest of the basket".
- The change in each group's costs is the share-weighted sum of item changes (first order).
- The band adds the items' quantiles as if they all moved together, so it is an upper bound on its width.

**Results:**
- After 6 months, a full closure adds 0.4–0.6 points to every group's costs, most of it through motor fuel.
- Car-owning middle-income households and owner-occupiers get the most (+0.55 to +0.61: the fifth and eighth income tenths, outright owners and mortgagors); social renters the least (+0.38).
- Energy-heavy budgets (the lowest-income tenth, +0.44; retired people, +0.46) are cushioned at first, because UK household energy follows the quarterly Ofgem cap.
- The year ahead from 2026-09: costs rise about 4.0–4.4%, slightly more for low-income and retired households, outright owners and social renters, least for the highest-income tenth and mortgagors.
- These are from the fans of 2026-10-25. The first version of this table, built on earlier fans, gave 0.5–0.7 points and 3.9–4.4%.

`report` reads the fans from `notes/cost-of-living-fans.csv` and skips this table if the file is missing.

## Limits

- **Average pay, not each household's income.** It misses benefits, taxes, hours and job loss. US average hourly pay rose in 2020 because low-paid jobs were lost first, a composition effect.
- **The Household Costs Indices are official statistics in development** and may be revised.
- **UK rents:** there's no CPI private-rent index here; the HCI covers private and social rents by group.
- **Euro-area pay is quarterly and starts in 2009** for the EA20 aggregate.
- **The scenarios hold nominal pay at its prior pace;** pay's response to a shock isn't modelled.

## Dashboard

A claude.ai dashboard shows these files as charts: real pay and inflation, the squeezes, essentials in
units of pay, US minutes of work, UK household groups and their spending shares, mortgage costs, the
Hormuz scenarios, and the sources table. Its data are saved snapshots of the notes, not live feeds;
model outputs are labelled as such on the page. To refresh it, re-run `report`, then
`household_dash.py`, and upload the files again.

## Reproduce

```bash
uv run experiments/household.py fetch
uv run experiments/household.py report
uv run --no-project --with numpy --with pandas --with scipy --with openpyxl python experiments/household_dash.py
uv run --no-project --with pytest --with numpy --with scipy --with pandas --with xlrd --with openpyxl pytest -q tests/test_household.py
```
