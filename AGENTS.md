# OxHack26: notes for the coding sessions

OxHack 2026. **TODO:** track, dates and the hard submission lock (copy them from the event brief
into `Context/event-rules.md`, then put the lock time here).

Read in this order at the start of every session:

1. `Context/event-rules.md` and the track brief in `Context/`: rules, deliverables, judging.
2. `docs/design.md`: the product (oil flow through Hormuz and its knock-on effects). Pitch work
   also reads `docs/pitch.md`; front-end work also reads `docs/ui.md`.
3. `coord/PROTOCOL.md`: each human runs a coding session; Linear team `OXH` (workspace
   `sotonship`) is how we talk. Find your lane and marker there, read the Linear document
   "STATE, read first", then start the watcher
   (`uv run --no-project python coord/linear_bus.py watch` in the background).

Ground rules:

- Every number shown in the app or pitch says where it came from and when it was collected.
  Synthetic data is labelled synthetic. Cached data is never shown as live.
- No API keys in git or Linear. This repo is public.
- Stay in your lane's paths (see PROTOCOL.md). Shared files change through a PR.
- Commits carry only the human's name: no `Co-Authored-By` lines for an AI model, no AI session
  links, and never an AI tool as author or committer.
- **TODO:** add the event's rules on AI use and provenance once we have them.

Commands (oil-price and knock-on experiments; see `docs/oil-price-model.md`):

- Tests: `uv run --no-project --with pytest --with numpy --with scipy --with pandas pytest -q tests`
- Lévy models: `uv run experiments/non_gaussian.py`, `uv run experiments/levy_fourier.py check|fit|rolling|report`
- Knock-on links: `uv run experiments/oil_chain.py`
- Regions, industry, AIS and fuel flows: `uv run experiments/macro_data.py`, `uv run experiments/macro_nn.py check|fold|ablate|final|report`,
  `uv run experiments/flow_price.py`, `uv run experiments/hdi_link.py` (see `docs/macro-ensemble.md`)
- Emergency oil stocks (buffer on the flow → Brent link, cover by country): `uv run experiments/reserves.py` (see `notes/reserves.md`)
- Cost of living by basket item: `uv run experiments/cost_of_living.py events|fit|check|report` (see `docs/cost-of-living.md`)
- Cluster runs: `docs/iridis.md`
