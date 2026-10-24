# Strait flow estimator on synthetic scenarios

Generated 2026-10-24 15:58 UTC by `uv run experiments/strait_flow.py`. **All ships are SYNTHETIC**: each scenario is calibrated so the true laden outbound flow matches a published figure, then the estimator sees only what AIS and two radar passes would show. Units: million barrels/day.

| Scenario | True (synthetic) | Seen on AIS | Bridged gaps | Never seen (radar) | Estimate (90% range) |
|---|---|---|---|---|---|
| Pre-war (EIA 2024 average) | 21.6 | 20.4 | 0.0 | 1.3 | 21.8 (20.0–24.6) |
| Aug 2026, trackers' view (~3.5 mb/d visible) | 6.1 | 2.4 | 0.5 | 3.3 | 6.2 (3.8–11.2) |
| Sep 2026, satellite view (~8.9 mb/d) | 8.2 | 3.8 | 1.1 | 3.0 | 7.9 (5.7–12.7) |

Method and assumptions: `docs/strait-live-data.md`.
