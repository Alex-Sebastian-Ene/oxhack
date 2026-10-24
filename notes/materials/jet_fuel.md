# Jet fuel: production, crude inputs, trade (research desk, 24 Oct 2026)

Data for the materials globe: `jet_fuel.json` (machine-readable, one source per row).

**How collected:** web search on 24 Oct 2026. Our sandbox could not open EIA, JODI or the Energy
Institute pages, so **every figure is from search-result snippets** of the cited pages. Rows say
"derived" where we did arithmetic on sourced numbers and "unconfirmed" where we found no reliable
figure. There is no clean country table of jet/kerosene output (EIA International, JODI, OPEC ASB
were unreachable), so production is assembled from national sources and is incomplete.

## Production (2025, kb/d)

World ~7.7 mb/d, using IEA 2025 jet/kerosene demand as a proxy for output.

- **United States ~1,820:** EIA data (Jan–Nov average) via OPIS.
- **China ~1,275:** NBS kerosene, converted at 7.9 bbl/t; includes non-jet kerosene.
- **South Korea ~450:** derived from domestic use plus exports; unconfirmed.
- **India ~370:** ATF output, about FY2024.
- **Kuwait ~270:** derived from exports.
- **Russia 263:** Energy Intelligence.
- **Japan ~220:** unconfirmed.
- **Saudi Arabia 156:** GASTAT, 2023.

## Trade

- **Seaborne jet:** about 1.8 mb/d in 2025, of which about 24% passed Hormuz (Argus citing Kpler).
- **Top exporters:**
  - South Korea, ~280–300 kb/d (Kpler via CNN);
  - Kuwait, ~260 kb/d (Windward);
  - China, ~460 kb/d gross including bonded aviation fuel;
  - United States, 219 kb/d (EIA).
- **Europe:** imported a record ~550 kb/d, with the Middle East about 52–75% of it (S&P ship tracking vs IEA). Kuwait alone is about 27%.
- **US West Coast:** 85% of its jet imports come from South Korea.

## Crude slates of the big refiners

Shares of crude imports, with sources per row in the JSON.
- **United States:** Canada 63%.
- **China:** Russia 17%, Saudi Arabia 14%, Iraq 11%, "Malaysia" 11% (largely relabelled Iranian).
- **India:** Russia 33%, Iraq ~20%, Saudi Arabia ~15%.
- **South Korea:** Saudi Arabia 34%, US 16%, UAE 11%, Iraq 11%.
- **Japan (FY2024):** UAE 44%, Saudi Arabia 40%.

**2026 shifts:** Russia passed 50% of India's imports in June; the US share of Japan's imports reached 36% in July.

## Oil-price link

- **Normal crack:** in 2025 jet averaged $90/bbl against Brent at $69, a crack of about $21.
- **2026 crisis:** the NWE crack averaged about $90 in March, and USGC jet hit a record $4.73/gal on 2 Apr.
- **Airline costs:** IATA's 2026 forecast puts fuel at 31.4% of airline costs, up from 25.4% in 2025.
- **Pass-through:** the globe uses Seb's Bayesian response (+8.2% jet per +10% Brent at 12 months) and the OXH-4 supply-shock range (13–15%).
