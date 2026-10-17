# Past cruise calls (SOT-6): source check

Checked Fri 16 – Sat 17 Oct 2026 by Keanu's Claude. Code: `src/sotonship26/data/cruise_history.py`.

## Correction, Sat 17 Oct 2026 08:00

The "dead end" verdict on Wayback copies of the schedule *page* below was wrong. Only the 2023–24
captures were checked, and those have no rows. Seb's session found four later captures of the VTS
cruise schedule HTML pages (2024-01-13, 2024-09-25, 2025-07-04, 2025-12-08) that do list calls: 792
calls on 625 of 912 days. That is now on main in `demo/webtris_backtest.py`, with the method and
results in `docs/backtest.md`. The raw captures and call list stay in gitignored `data/raw/`.

Two things still stand:

- **Whether we may use them is for the humans to decide.** ABP's terms allow personal reference
  with ABP acknowledged; this is a public hackathon product that publishes aggregates.
- These are provisional plans captured months ahead, not actual berthings. 2026 calls come from the
  8 Dec 2025 plan, so late changes and cancellations are missing.

The table below is the original check, kept for the record.

## Result (original, Fri 16 Oct)

**No source we're allowed to collect automatically has day-by-day Southampton calls for
2024 – Jun 2026.** The loader is built and tested, but the historic table is empty: 0 calls and 0
of 912 days covered. The backtest cannot label past cruise days until a human gets permitted
history (see "What would unblock it").

| Source | Has 2024–26 calls? | Can we collect it? | Verdict |
|---|---|---|---|
| VTS feed `southamptonvts.co.uk/xml/sotcruiseship.xml` (ABP, official, has berths) | No. It lists about 15 weeks ahead, and calls drop off once they happen | Yes; robots.txt allows everything (`Disallow:` empty), and Ed's loader already uses it | Use it from now on: daily snapshots build history going forward |
| Wayback Machine copies of that feed | No. CDX returns 0 captures of `/xml/sotcruiseship.xml` | n/a | Dead end |
| Wayback copies of the schedule page (2023–24) | No. The table was filled server-side from `D:\ftp\...DandGMediaCruiseShips.xml`, so the archived HTML has no rows | n/a | Dead end |
| cruisetimetables.com | Yes, by day | **No.** robots.txt has `User-agent: ClaudeBot` → `Disallow: /` | Excluded |
| cruisemapper.com | **No.** Asking for `?month=2024-06` returns Jan 2026 onward | **No.** Terms: "You must not conduct any systematic or automated data collection activities (including ... scraping ...) without our express written consent" | Excluded |
| cruisedig.com | **No.** The month filter only goes forward (asking for 2024-06 returns Jun 2027) | robots.txt allows | Useless for history |
| gangwaze.com | Unknown | **No.** Vercel bot checkpoint | Excluded; we don't get around bot challenges |
| crew-center.com | Yearly totals only (2024: 448 calls, ~1.44M passengers; calls per ship) | **No** for the schedule pages, which sit behind a Sucuri JS challenge | Totals are usable as a sanity check, not as labels |

## What would unblock it (for the humans)

1. **Ask council staff on Saturday (SOT-15)** whether the traffic team or ABP liaison holds the
   2024–25 cruise call list (date, ship, berth). Even one season is enough to train on.
2. **Ask ABP / Southampton VTS** (southamptonvts@abports.co.uk) for the 2024–25 call list for a
   student project, attributed and not redistributed.
3. **Ask CruiseMapper for written consent** (their terms allow it with consent).
4. Whatever arrives goes in `data/raw/cruise_history/manual_calls.csv` (`ship, arrival, source`,
   optional `imo, departure, berth, terminal, passengers, source_url`). Add
   `manual_coverage.csv` (`start, end, source`) for the ranges the source lists **completely**.
   Then rerun `python -m sotonship26.data.cruise_history`.

## Going forward

`python -m sotonship26.data.cruise_history --snapshot` saves today's VTS feed. The first snapshot
was taken 2026-10-16 23:00Z: 108 calls, 22 ships, 17 Oct 2026 – 29 Jan 2027, with 105 of 107
days covered. A daily snapshot through the season gives a clean, official, berth-level history,
but that only helps from now on and not this weekend's backtest.

## Passenger capacity

The VTS rows match on IMO against `ship_capacity.csv` (SOT-17, Edward's loader on main). With no
historic calls, there are no extra historic ships to look up yet, so `ship_capacity_history.csv`
has not been created. `load_capacities()` reads it when it exists.
