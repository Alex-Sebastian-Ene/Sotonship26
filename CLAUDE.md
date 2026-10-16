# Sotonship26: notes for Claude Code

SotonShip 2026, Southampton City track. Hacking ends **Sun 18 Oct 13:00** (hard lock).

Read in this order at the start of every session:

1. `Context/event-rules.md` and `Context/track-southampton-city.md`: rules, deliverables, judging.
2. `docs/design.md`: the product (cruise-day traffic forecast for the council's traffic team).
3. `coord/PROTOCOL.md`: three humans each run a Claude; Linear team `SOT` is how we talk. Find
   your lane and marker there, read the Linear document "STATE, read first", then start the
   watcher (`python coord/linear_bus.py watch` in the background).

Ground rules that cost points if broken:

- Every number shown in the app or pitch says where it came from and when it was collected.
  Synthetic data is labelled synthetic. Cached data is never shown as live.
- No API keys in git or Linear. No raw VTS pages or CSVs in git (redistribution not permitted).
- Record AI-generated parts in the README provenance section.
- Stay in your lane's paths (see PROTOCOL.md). Shared files change through a PR.

Commands: `uv run pytest`, `uv run ruff check .`, `uv run sotonship-eval --scenario streets`.
