# Sotonship26: notes for the coding sessions

SotonShip 2026, Southampton City track. Hacking ends **Sun 18 Oct 13:00** (hard lock).

Read in this order at the start of every session:

1. `Context/event-rules.md` and `Context/track-southampton-city.md`: rules, deliverables, judging.
2. `docs/design.md`: the product (cruise-day traffic forecast for the council's traffic team).
3. `coord/PROTOCOL.md`: three humans each run a coding session; Linear team `SOT` is how we talk. Find
   your lane and marker there, read the Linear document "STATE, read first", then start the
   watcher (`python coord/linear_bus.py watch` in the background).

Ground rules that cost points if broken:

- Every number shown in the app or pitch says where it came from and when it was collected.
  Synthetic data is labelled synthetic. Cached data is never shown as live.
- No API keys in git or Linear. No raw VTS pages or CSVs in git (redistribution not permitted).
- Don't name the AI tool in code, docs, notes, commit messages or PRs (no bylines, co-author
  trailers or "generated with" lines). The README's provenance section says which parts are
  AI-generated, as the event rules require; keep it current there, in general terms. The setup
  commands in `coord/` are the only exception.
- Stay in your lane's paths (see PROTOCOL.md). Shared files change through a PR.

Commands: `uv run --extra cpu pytest`, `uv run ruff check .`. The forecast page is built by the `demo/` scripts
(see `cluster/iridis/agents_ppo_cpu.slurm` for the order); `sotonship-eval` and `sotonship-train` belong to the
parked pedestrian and waterway design.
