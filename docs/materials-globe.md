# Materials Globe: how oil moves reach steel, jet fuel and the rest

Written 24 Oct 2026. Page: `ui/globe/index.html` (opens offline). Data: `notes/materials/`.
Build: `uv run experiments/globe_geo.py`, `uv run experiments/globe_data.py`, then
`uv run experiments/globe_flags.py`. One-file build:
`uv run experiments/bundle_page.py ui/globe out.html`.

## What it shows

1. **Pick a material** (steel, jet fuel, aluminium, nitrogen fertiliser, polyethylene) from the left
   rail. **Made** (share of world output) and **Shipped** (exports) are drawn together. The layer in
   front is bright: its countries rise and glow. The other is faded: see-through columns on each
   country and thin arcs. Tap Made or Shipped, or the faded number on the card, to swap them.
2. **Click a country.** Made arcs fly in from the countries that supply its ingredients, for
   example China's iron ore from Australia (64% of imports) and Brazil (23%). Shipped arcs show its
   biggest sourced trade flows. Flags mark the countries, and green chips are domestic supply.
   Clicking the country again puts it back down. **More** opens everything our tables hold on it,
   plus an optional AI brief (`docs/country-briefs.md`).
3. **Click ⊕ on an ingredient.** The globe re-colours by who produces that ingredient worldwide,
   for example Guinea's 34% of bauxite, and still shows what reaches the chosen country.
4. **Drag Brent.** Each material's badge shows its modelled price change in 12 months. The band
   shown is the 90% interval of the average effect only, so single outcomes vary more (Seb, OXH-3).
   Jet fuel also shows the supply-shock range from past disruptions (OXH-4).
5. **Info buttons.** About explains the view with pictures. Sources lists every dataset, supplier
   link and trade flow, each with its source pages and year.

## Why these choices

- **Materials:** these five have direct Hormuz exposure.
  - Jet fuel: the Gulf is about 20% of seaborne jet.
  - Fertiliser: the Gulf is 36% of urea exports.
  - Aluminium: Gulf smelters are 8% of world output, and two were hit by strikes on 28 Mar 2026.
  - Steel: exposed through coal, freight and gas-based ironmaking (DRI) plants.
  - Polyethylene: about 15% of world capacity is in the Middle East, and Asian crackers run on Gulf
    naphtha.
- **Polyethylene output is a proxy:** no PE-only country table was found, so the globe uses each
  country's share of PE, PP, PET and PS output together, and says so. Polyethylene exporters by
  country are still unconfirmed and stay off the map.
- **Supplier links, not full trade matrices.** For each big producer we show where its
  ingredients come from, as shares of its imports, or its domestic share. That is what the
  "resource X is made in country A from country B's inputs" story needs, and it keeps every
  number traceable to one source. Full bilateral matrices (UN Comtrade, CEPII BACI) are the
  upgrade path.
- **Shares vs volumes.** Some export tables have no world total for the same year (steel, scrap,
  crude, aluminium value). There the globe colours by size relative to the largest and prints the
  volume, rather than a share we can't back up. A share estimated from the table's own ratio is
  marked "≈".
- **Oil → price** comes from Seb's Bayesian pass-through model (`notes/macro-bayes-responses.csv`
  on `seb/macro-nn`, commit b6886cf): the 12-month response to a one-off ±10% Brent move. Its 90%
  interval covers the average effect only.
  Rises and falls use separate rows because they differ, scaled by ln(1+x)/ln(1.1) or
  ln(1+x)/ln(0.9). Steel and aluminium show "?" until Seb fits them (OXH-5).
- **Offline globe.** globe.gl (MIT) is bundled in `ui/globe/vendor/` with its licence, and so are
  the coastlines (Natural Earth, public domain) and the flags (flag-icons, MIT, via
  `uv run experiments/globe_flags.py`). No map tiles, no CDN, so the demo
  survives venue Wi-Fi.

## Data quality (read before quoting)

Every figure came from web searches on 24 Oct 2026. Most primary sites (worldsteel, USGS, IEA,
Comtrade, OEC, EIA) were blocked from our sandbox, so values are from **search-result snippets** of
the cited pages. Each row in `notes/materials/*.json` carries its source URL and year; rows marked
"derived" are our arithmetic, and rows marked "unconfirmed" are flagged as such. Known gaps:
- the USGS world total for iron ore;
- coking coal production by country;
- South Korea's 2025 ore and coal origins;
- the ammonia world total (an assumed 150 Mt N);
- polyethylene output by country (proxy) and exporters;
- urea and naphtha world totals.

Re-check headline numbers against the primary PDFs before the pitch.
