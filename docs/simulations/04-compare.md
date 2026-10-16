# 04 · Compare

**Page:** `frontend/compare.html` · **Code:** `frontend/js/sims/compare.js`

## Question it answers

What changes if something changes? This is the "what if" page for the council's events team, and
the way to show the RL levers working.

## What you see

Two maps side by side (stacked on a phone), running the same sampled day with the same seed. Pick
a scenario for each side. Pan or zoom one and the other follows. The panel shows **B minus A** so
far: busiest footway, people turned away, people late for their ship or train, and venue spend,
plus a table of venue peaks sorted by the biggest difference. The bottom chart overlays people
walking in A and B.

Scenarios:

| Scenario | What changes | RL lever it mirrors |
| --- | --- | --- |
| Baseline | Three ships, dry, shortest paths | none |
| Rain | Parks lose pull, shops and museums gain | none (exogenous) |
| Staggered disembarkation | Walkers released over 5.5 h instead of 3.5 h | Metering (`hold` in `rl/env.py`) |
| Canute Road closed | Edge between Dock Gate 4 and Ocean Village removed | Closure (cost → ∞) |
| Stewards at Dock Gate 4 | Terminus Terrace cost × 4, Platform Rd × 0.6 | Steering (edge cost scale) |
| Crowd-aware wayfinding | Everyone routes around dense footways | Steering, everywhere |
| Fourth ship at Mayflower | Adds a 5,200-passenger turnaround | none (demand) |
| Rail disruption (45% walk) | More passengers on foot | none (demand) |

## Design decisions

| Decision | Why |
| --- | --- |
| Same seed on both sides | Every difference comes from the change, not from sampling noise. Without this, two runs of the same scenario differ and the comparison means nothing. |
| Each side gets its own graph instance | Edge costs and closures are per scenario; sharing a graph would leak one side's closure into the other. |
| Levers expressed as edge cost scaling, closures and demand metering | These are exactly the RL environment's action space, so a policy's action can be shown here as a scenario. |
| Show B − A only, with sign | The reader wants the effect, not two sets of numbers to subtract in their head. |
| Venue table sorted by absolute difference | The venues a change affects most float to the top, whichever way. |
| Linked cameras | You compare the same street in both; unlinked maps make that a chore. |
| Opens at 09:30 | Both maps busy from the first frame. |

## Backend hooks

- Add a scenario that loads a trace on one side: "trained policy" against "gravity model".
- Scenario definitions are plain objects in `SCENARIOS`; the backend could emit them.

## Next

- Run each scenario across many seeds and show the difference as a distribution.
- Draw closed edges more strongly and add a marker where stewards stand.
