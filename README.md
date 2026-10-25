# OxHack26

Our team's project for OxHack 2026: estimate how much oil is really flowing through the Strait
of Hormuz from live ship data, ghost tankers included, and show what changes in that flow mean
for oil prices, the Fed's interest rate and the cost of living.

- **Event rules and track:** [Context/event-rules.md](Context/event-rules.md)
- **Design:** [docs/design.md](docs/design.md), with the pitch in [docs/pitch.md](docs/pitch.md)
  and the UI in [docs/ui.md](docs/ui.md)
- **Technical notes:** the oil-price model in [docs/oil-price-model.md](docs/oil-price-model.md),
  which knock-on links hold up in [docs/knock-on-validation.md](docs/knock-on-validation.md), and
  cluster runs in [docs/iridis.md](docs/iridis.md); the multi-region ensemble with industry, AIS,
  pipeline and fuel-flow inputs, the AIS flow → Brent link and HDI in
  [docs/macro-ensemble.md](docs/macro-ensemble.md); the cost of living built up from basket items
  (food, household energy, motor fuel, air fares, restaurants) in the US, UK and euro area in
  [docs/cost-of-living.md](docs/cost-of-living.md)
- **The app:** open [ui/app/index.html](ui/app/index.html) in a browser (no server needed); how it is built, layer
  by layer, is in [ui/app/README.md](ui/app/README.md), and its Gemini panels in
  [docs/country-briefs.md](docs/country-briefs.md)
- **How the team works:** [coord/PROTOCOL.md](coord/PROTOCOL.md). New laptop? Start with
  [coord/BOOTSTRAP.md](coord/BOOTSTRAP.md).
