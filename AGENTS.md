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

Commands: TODO once there is code.
