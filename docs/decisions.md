# Design decisions

The choices that shaped the project, what each one was for and the evidence behind it. Dates are
Fri 16 to Sun 18 Oct 2026. Issue numbers (SOT-n) refer to the team's Linear board; the deeper
write-ups are linked.

## Product

### 1. Forecast vehicle traffic for the council, not passengers on foot

- **Decision.** The product forecasts cruise-day road congestion for Southampton City Council's
  traffic team. The first design (pedestrian crowding at the terminals and craft in Southampton
  Water) and the pedestrian prototype were parked.
- **Why.** The footways round the terminals are wide enough that walking passengers do not change
  any decision the council makes. Road congestion does: the council has a duty to keep traffic
  moving (Traffic Management Act 2004, s.16) and can set the days roadworks run when disruption is
  likely (New Roads and Street Works Act 1991, s.56).
- **Evidence.** In 2011 the council's own transport manager told councillors that cruise growth
  "causes significant congestion, especially at weekends, by Dock Gate 4", and that it gets worse
  when two or more large ships coincide with a football match. Sources in
  [notes/local-evidence.md](../notes/local-evidence.md).
- **Trade-off.** The waterway and pedestrian code stays in `src/sotonship26/` (`data/streets.py`,
  `data/waterway.py`, `data/tides.py`, `demand/`, `routing/clear_channel.py`, `rl/`) but nothing
  in the product uses it.

### 2. Recommend, never act

- **Decision.** The page suggests actions (marshals at a gate, a sign message, holding a roadworks
  permit) with a time window and the organisation that owns each one. An officer approves or
  declines; nothing is switched automatically.
- **Why.** The port runs the gates, the cruise lines own disembarkation and check-in, and the
  council owns signs and permits. A tool that pretended otherwise would not be used.

### 3. A single static page instead of a hosted app

- **Decision.** The forecast is a self-contained HTML page (`demo/page.html` plus data), built in a
  batch run, rather than the Streamlit app first planned in [design.md](design.md).
- **Why.** The heavy part (thousands of simulated days) runs once on a cluster; the officer only
  reads the result. A static page loads offline, can be shared privately, and shows exactly the
  run it was built from, with the build time on screen.
- **Trade-off.** Road-closure what-ifs are precomputed for the busiest and permit days, not run on
  demand.

## Forecast

### 4. Give odds and ranges, not a single number

- **Decision.** Each date is simulated many times (30 samples per date in the published build).
  The page shows the chance each road goes over 85% of capacity per 15 minutes and a 10–90% range
  for the cruise effect.
- **Why.** The schedule is provisional (most calls have no clock time until about six days out),
  passenger loads vary, and weather and incidents happen. An officer deciding a week ahead needs to
  know how sure the forecast is. 85% of capacity is the usual UK design threshold for a road
  nearing its limit.
- **How the cruise effect is isolated.** Every sampled day is run twice, with and without the
  ships, using the same random draws, so the difference is the ships' effect on that day rather
  than noise between two different days.

### 5. The real road network, with a fast 15-minute model

- **Decision.** OpenStreetMap roads (lanes, speed limits, one-ways, dock gates), zones from land
  use, and a macroscopic model: every 15 minutes each origin-destination flow splits over up to
  three real routes, roads slow down with a BPR curve, and traffic that cannot pass a full road
  waits for the next 15 minutes.
- **Why.** It is fast enough to run 44 dates × 30 samples × 2 (with and without ships) in under
  20 minutes on 64 cores, which a microsimulation is not.
- **Check.** The same sampled days were run through the Eclipse SUMO microsimulator
  ([sumo-check.md](sumo-check.md)). SUMO, uncalibrated, gridlocked at the macro model's demand,
  and the comparison exposed demand on the west side two to three times the observed peak traffic.
  That led to fix 6.

### 6. Fit to public counts, then fix what the counts expose

- **Decision.** Trips within the area are scaled to the council's Portswood traffic counts (July
  2024); county and through traffic to DfT annual counts at the edge of the area; port lorries to
  DfT lorry counts; cruise assumptions to the cruise uplift learned on the M271 (decision 9).
- **Why.** Every invented total in a traffic model is a guess until it meets a count. The page
  shows the fit tables so the remaining gaps are visible.
- **What it caught.**
  - Queued traffic was counted again every 15 minutes, which inflated the motorway loads.
  - Two links were missing at the edge of the map: the M27 eastbound through junction 3, and the
    A326 northbound into junction 2.
  - The M3 southbound south of junction 13 had 2 of its 4 lanes.

  These were fixed on 17 Oct ([west-side-counts.md](west-side-counts.md)). Buses run through the
  modelled roads were 2 to 5 times later on Portswood Road than the council measured, which led to
  the capacity change in [queues.md](queues.md).

## The AI and how it is tested

### 7. Beat the strongest simple rule, and say where we don't

- **Decision.** Every learned model is scored against baselines a planner would actually use,
  including the brief's own "last comparable cruise day". Gains are quoted with a 90% interval from
  resampling whole test weeks.
- **Why.** A gain over a weak baseline says little. Resampling days instead of weeks made the
  intervals too narrow, because neighbouring days are alike.
- **Result.** For everyday traffic at M3 J14, ridge regression on calendar features (including
  Southampton school holidays) beats a five-week year-ago median by 6.6% (90% interval 0.5–12%)
  over 355 held-out days. On the M271 it does not beat the year-ago rule, and the write-up says so
  ([notes/flow-forecast.md](../notes/flow-forecast.md)).

### 8. Honour the publication delay

- **Decision.** Models are refitted only on counts that would have been published by the forecast
  date: National Highways publishes WebTRIS counts about 105 days late.
- **Why.** A backtest that uses yesterday's counts promises an accuracy the council cannot get.
  With the delay applied, the learned cruise model's error rises 3% and the last-comparable-day
  baseline's 19% ([ridge-history.md](ridge-history.md)).

### 9. Learn the cruise effect from archived schedules

- **Decision.** Past cruise calls come from Internet Archive captures of the VTS schedule page
  (team decision, 17 Oct, SOT-21). A gradient-boosted quantile model learns the 15-minute cruise
  uplift on the M271 from them, and the simulator's cruise assumptions are fitted to that uplift.
- **Why.** There is no open list of past calls. ABP's terms allow personal reference with
  acknowledgement, so raw captures stay out of git and only aggregates are published.
- **Result and limit.** On 179 held-out days (Jan to Jun 2026) the model's error is 877 vehicles a
  day, against 1,233 for the last comparable cruise day. Most of that gain is the calendar; the
  ship data adds 2% per 15 minutes ([backtest.md](backtest.md)). The sensor is 4 to 7 km from the
  terminals, because dock-gate traffic is not counted publicly.

### 10. Reinforcement learning as a decision layer, with its caveats on screen

- **Decision.** A PPO policy (Stable-Baselines3) chooses every 15 minutes between metering
  disembarkation, moving check-in, signs and dock-gate marshals, on simulated days. It is tested on
  held-out sampled days against doing nothing, a simple rule and the page's ship-timing advisor.
- **Why.** The forecast says when roads fill; the officer's question is what to do about it.
- **Result.** It cuts congested road-hours by 2.9 a day and total cost by £10,724 a day against
  doing nothing, cheaper on 93% of 260 sampled days ([agents-and-ppo.md](agents-and-ppo.md)).
- **Caveats shown next to the numbers.**
  - An ablation shows most of the gain comes from marshals, whose 25% extra gate capacity is
    assumed, not measured.
  - The advisor is better on delay.
  - Signs were left on all day when free, so a stated sign cost was added and the plan is shown
    in windows of at least 30 minutes.

### 11. Individual vehicles to explain the forecast, not to make it

- **Decision.** For a few days, one sampled day is drawn as several thousand individual vehicles
  plus real bus routes moving on the map.
- **Why.** Moving traffic is easier to read than a heatmap. A test checks that the vehicles, times
  the number each stands for, add back up to the model's own flows.

## Data and trust

### 12. Every number says where it came from and when

- **Decision.**
  - Each figure is tagged Published or Modelled.
  - Sources carry their collection time, and the schedule shows when it was read.
  - Dates beyond the published schedule get a refusal, not a guess.
  - Synthetic inputs are labelled as such.
- **Why.** The event rules require it, and an officer needs to know which numbers are measured
  before acting on them.

### 13. Public data only, and no raw ABP data in git

- **Decision.** All inputs are public (OpenStreetMap, DfT, National Highways, ONS, Bus Open Data
  Service, Street Manager, the council and the club). Raw VTS pages, call lists and the built page,
  which embeds the schedule, stay out of the repository.
- **Why.** ABP's terms allow extracts for personal reference only.

### 14. Observed bus lateness from the live feed only

- **Decision.** Bus lateness on the day is read from bustimes.org's `/vehicles.json`, which
  republishes the Bus Open Data Service live feed, once a minute. Its per-trip pages are not used.
- **Why.** bustimes.org's robots.txt disallows `/api/` and `/trips/`, and the vehicle feed already
  reports each bus's delay against its timetable.

### 15. Heavy runs on Iridis, light runs on a laptop

- **Decision.** The full build (forecast, vehicles, PPO training) runs on the University of
  Southampton's Iridis cluster; scripts in `cluster/iridis/`. Laptops build reduced pages (fewer
  samples per date) from the same code, and the trained PPO model is committed
  (`models/ppo/1889084/`) so anyone can rebuild the page without the cluster.
