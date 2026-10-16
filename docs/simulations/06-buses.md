# 06 · Buses

**Page:** `frontend/buses.html` · **Code:** `frontend/js/core/transit.js`, `frontend/js/sims/buses.js`,
`frontend/data/buses.js` · **Data pipeline:** `src/sotonship26/data/buses.py`, `scripts/bustimes.py`

## Question it answers

What do late buses do to cruise passengers and the businesses waiting for them? A passenger with
luggage who waits 15 minutes for a late bus to the station is 15 minutes not spent in a café, and
may miss their train. Buses also run in Turnaround Day (a dropdown) and in Compare (scenarios "No
buses" and "Buses 10 min late"), so their effect reaches the staffing forecast.

## What you see

- Four bus lines drawn as thin parallel strokes, so a street served by three lines shows three.
  Stops are ringed dots. Hovering a stop lists its lines and how many people are waiting.
- Buses are small oriented capsules, filled by how late they are (green ≤1 min, amber 1–3,
  orange 3–5, red over 5) with a dark bar inside for how full they are, and their line code above.
- People waiting for a bus queue in a short row beside the stop. People riding disappear into the
  bus and reappear where they get off.
- A real-time **departure board** for any stop, amber on black like the signs in town: line,
  destination and minutes to go, with an expected time when the bus is running late.
- Controls: "Every bus later by" (0–20 min on top of the profile), no buses at all, restart.
- Running totals: boardings, gave up waiting, waiting now, late for ship or train. A table by line
  of buses out, mean lateness, the 90th percentile and the share over five minutes late.
- Charts: average lateness of buses on the road through the day, and people waiting at stops.

## How buses are modelled

| Piece | Model | Why |
| --- | --- | --- |
| Timetable | Departures from each end every `headwayMin` between `first` and `last`; the reverse direction is offset half a headway. Scheduled stop times assume 4.5 m/s plus 25 s at each stop. | The shape bustimes.org timetables reduce to for a corridor, and all the simulation needs. |
| Route | Shortest path between consecutive stops on the street graph, banned from footway-only (`door`), dock-estate and dock-gate edges. | Buses share the graph with walkers, so a road closure in Compare also cuts or diverts a line. A line a closure cuts in two is dropped, not teleported. |
| Lateness | Each departure draws L minutes from the line's profile for that hour (mean and 90th percentile, skewed right, capped at 2 min early). 40% of L is a late start; the rest is lost en route as a slower running speed. | Real buses are late at every stop and get later along the route. A pure late start would recover; pure slow running would start on time. The split is a guess to calibrate against collected data. |
| Dwell | 15 s plus 2 s per person getting on or off. | Crowded stops make buses later still, which is the cruise-morning effect worth showing. |
| Capacity | 80 people. People who do not fit wait for the next bus. | The `leftBehind` counter shows when a line is full. |
| Choosing the bus | After the policy picks a destination, the agent compares walking with the best bus journey: walk to a stop (≤9 min), half a headway's wait, ride, walk from the stop (≤9 min). Passengers with luggage (rail transfers, boarding passengers) ride when it is at least 5% faster; others only when it saves 30%. Trips under 8 minutes on foot are always walked. | Mode choice sits under the policy, not inside it, so the RL action space is unchanged. Passengers plan with the timetable, not live lateness: most do not check an app, which is exactly why lateness hurts. |
| Giving up | After one headway plus 7 minutes, or when waiting longer would make them miss their deadline, a waiting passenger walks instead. | Without it, a badly late line would strand people forever. "Gave up waiting" is a clean measure of the cost of lateness. |
| Departure board | Each upcoming departure is shown at its timetable time; a bus already on the road shows its expected time from its lateness at the last stop. | That is how a real-time sign behaves, including its blind spot: a bus that has not set off yet always looks on time. |

## The data: bustimes.org

bustimes.org republishes the Bus Open Data Service (timetables and live positions) with a public
JSON API. `src/sotonship26/data/buses.py` uses `/vehicles.json?xmin=&ymin=&xmax=&ymax=` for the
buses in a box around the city centre and `/api/trips/<id>/` for each bus's timetabled stops, then
works out lateness itself: project the bus onto its trip's stop-to-stop line, interpolate the aimed
time there, and subtract. Where the feed reports its own delay we keep it alongside, for
comparison.

```bash
uv run python scripts/bustimes.py collect --minutes 180 --every 60   # one row per bus per minute
uv run python scripts/bustimes.py export                              # -> frontend/data/buses.observed.js
```

Then change the import at the top of `frontend/js/core/transit.js` from `buses.js` to
`buses.observed.js`. The Buses page reads `BUS_META` and swaps the "Synthetic" chip for the
collection date.

Decisions in the pipeline:

- **Compute lateness rather than trust a field.** Not every operator's feed reports delay, and
  ours is consistent across operators. Sightings more than 250 m from their trip's route
  (diversions, depot runs, wrong trip ids) are dropped rather than guessed.
- **Polite by construction.** Requests are at least 1.5 s apart, trips are cached on disk (a trip's
  timetable does not change during the day), and there is a descriptive User-Agent. bustimes.org is
  run by one person.
- **Aggregate before it reaches the frontend.** The frontend gets lateness by line and hour (mean
  and 90th percentile) and each line's stops snapped to our graph nodes (within 200 m), not raw
  vehicle tracks. That is all the model needs, and aggregates are the safest thing to publish. The
  underlying data is OGL v3.0 via BODS; check bustimes.org's terms before redistributing raw rows.
- **Raw rows stay out of git** (`data/raw/` and `data/cache/` are gitignored).
- Tests in `tests/test_buses.py` cover trip parsing (including times past 24:00), interpolated
  lateness, off-route rejection, tolerant vehicle parsing and the CSV round trip.

## Honest limits

- **Nothing here is real bus data yet.** bustimes.org was blocked by the build environment's
  network policy, so the four lines in `frontend/data/buses.js` are schematic corridors on our own
  graph and the lateness profile is invented (later in the peaks and on the dock roads on cruise
  mornings). The page says so on the map. The API field names in `buses.py` are from memory and
  unverified; the parser skips records it cannot read rather than failing.
- The export estimates headway and service hours from the trips it happened to see, so a short
  collection underestimates frequency.
- Buses are not slowed by crowds of walkers, and walkers are not slowed by buses.
- The coaches and cruise-line shuttles that carry most passengers to the station are not modelled.
  They would be the next line to add, running only while a ship is disembarking.
