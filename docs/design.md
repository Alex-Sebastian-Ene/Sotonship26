# Cruise-day traffic forecast: design plan

**Status:** proposal for team discussion, Fri 16 Oct 2026 22:30. It replaces the streets + waterway
design in the README. No code has changed yet. Drafted with Claude Code; record that in the README
provenance section.

## 1. The product

> We help Southampton City Council's traffic management team decide which cruise days and hours
> need traffic marshals, sign messages and a hold on roadworks around the docks, using a
> probabilistic forecast built from the VTS cruise schedule and learned from observed traffic.

**User:** the council's traffic management / network management officers (the ROMANSE control
room). Confirm the team name and their current cruise-day routine with council staff at the event.

**Decisions it supports**

1. **Roadworks and closures:** approve, condition or move a permit on a dock corridor when that day
   is a heavy turnaround day.
2. **Plan the day a week ahead:** sign messages, signal plans, marshals at dock gates, requests to
   ABP or the police.
3. **Spot clashes:** match days at St Mary's, city events and big turnaround days on the same roads.

**Buyer:** Southampton City Council (network management duty under the Traffic Management Act
2004). Second buyer: bus operators whose routes cross the dock corridors. Second city: the highway
authority of any UK cruise port (Portsmouth, Dover, Liverpool, Tilbury). It needs OSM, DfT counts
and that port's schedule.

**Out of scope:** changing signals or signs automatically, traffic inside the port, the waterway,
real-time incident detection.

## 2. What the user sees

| Screen | Shows | Decision it serves |
|---|---|---|
| **Calendar** (next 4–6 weeks, as far as VTS publishes) | Each day coloured by risk; ships, terminals and passengers listed; clash icons for roadworks and match days | Which days need attention |
| **Day view** | Corridor × 15-min heatmap of P(congested); map of the dock roads at the chosen time; dock gate busy windows | When and where to put marshals and sign messages |
| **What-if** | Close or restrict a road (a roadworks permit) and rerun; before/after risk on every corridor | Approve, condition or move the permit |

Always on screen: when the schedule was collected, the year of the traffic counts, the model
version, and a **measured vs modelled** badge on each corridor (only a few roads have sensors).

Build it with Streamlit and pydeck: one Python app, runs live in the pitch. Precompute the calendar
in a batch job; run the what-if live with fewer Monte Carlo samples.

## 3. How the forecast works

```
VTS schedule ──► vehicles per dock gate per 15 min ──┐
                 (mode split, timing, approach road)  │
OSM major-road network + lane capacities ─────────────┼─► route on candidate paths ─► V/C per road per bin
DfT counts × time-of-day profile (background load) ───┘   (PathFinder negotiation)        │
                                                                        aggregate to ~10 named corridors
                                                                                           ▼
                                Monte Carlo over 200 sampled days ─► P(V/C > 0.85), P(V/C > 1), delay
                                                                                           │
Observed 15-min traffic on approach roads ─► learn the uncertain parameters ◄──────────────┘
                                             backtest against baselines on held-out days
```

### 3.1 Vehicles per ship call

| Mode | Road movements per vehicle | People per vehicle | PCU | Timing |
|---|---|---|---|---|
| Car drop-off / pick-up | 2 (in and out) | ~2.5 | 1 | Embark curve in; disembark curve out, arriving ~30 min early |
| Park & cruise | 1 (in on embark, out on disembark) | ~2.5 | 1 | Same curves |
| Taxi / private hire | 2 | ~2 | 1 | Same; many trips start or end at Central station |
| Coach | 2 | ~45 | ~2.5 | Arrive before disembarkation; block departures |

- **Mode shares:** sampled from a Dirichlet distribution around starting guesses, marked `calibrate` in
  config until ABP figures or the calibration replace them.
- **Approach roads:** a share per approach (M271/A35 from the west, A33 from the north, A3024/A335
  from the east, city centre, Central station). Also `calibrate`.
- **Terminal → dock gate:** a config table filled in by hand. Verify it against ABP's published
  directions to each terminal.
- **Reuse:** `TurnaroundParams` timing curves, load factor and ship delay from
  `demand/passengers.py`; binning from `demand/bins.py`.

### 3.2 Road network

- **Graph:** OSM `drive` network within ~4 km of the docks, filtered to trunk, primary, secondary,
  tertiary and the dock access roads. That gives a few thousand nodes, not tens of thousands.
- **Directed:** cars care about direction, one-way streets and separate carriageways.
  `data/streets.py` collapses to an undirected graph; the road loader must not.
- **Capacity:** per lane per road class from config (`calibrate`), with lanes from the OSM `lanes` tag
  or a per-class default.

### 3.3 Background traffic

DfT annual average daily flow by direction at count points in the area × the DfT time-of-day and
day-of-week profile gives background vehicles per bin on counted roads. Uncounted roads get a
road-class default share of capacity. Background is preloaded onto each road before cruise traffic
is routed, so V/C = (background + cruise) / capacity.

### 3.4 Routing

- **Candidate paths:** for each (approach, gate, direction), precompute ~5 sensible paths with
  `nx.shortest_simple_paths`. That's about 36 OD pairs.
- **Assignment:** PathFinder's negotiation picks among those paths instead of running Dijkstra each
  time, which is orders of magnitude faster. It also makes the explanation simple: "drivers choose
  between a few real routes".
- **Packets:** split each flow into packets of ≤20 PCU so traffic can spread over routes.
- **Bins:** trips in this area take under 15 minutes, so routing each bin on its own is acceptable for
  vehicles.
- **Not modelled:** queues backing up into the next bin, and signal timings.
- **Delay:** BPR curve, t = t₀(1 + 0.15 (V/C)⁴).

### 3.5 Outputs

- **Per corridor per bin:** P(V/C > 0.85) ("at risk", the UK ratio-of-flow-to-capacity design
  threshold), P(V/C > 1) ("over capacity") and expected delay.
- **Corridor V/C:** the worst road segment in that corridor.
- **Day risk:** expected PCU-hours above 0.85, used to colour the calendar.
- **Corridors (~10, names to verify):** Western Esplanade, West Quay Road, Mountbatten Way / A33
  Millbrook Road, Redbridge Road / A35, M271 southern end, Town Quay / Platform Road, Canute Road,
  Central station taxi approach, and one approach per dock gate used by cruise terminals.

## 4. The AI and how we test it

**What is learned:** the parameters we currently guess: mode shares, approach shares, timing offsets
and background scale.

**What it learns from:** observed 15-minute traffic on the approach roads on past cruise days. The
data spike (`notes/data-spike.md`) picks the source; National Highways WebTRIS on the M271 is the
lead candidate.

**Target:** cruise uplift, meaning observed flow minus the median for the same weekday and time on
non-cruise days.

**Method:** fit the parameters with Optuna (already a dependency) to minimise simulated-vs-observed
uplift on training days. Report the fitted values with ranges. Stretch goal: a gradient-boosted
quantile model on the remaining error.

**Product dependency:** without the learned parameters, the forecast is a stack of guesses. With
them it is tested.

**Backtest**
- Train on calls up to a cut-off date and test on later days. Report the number of test days.
- Metrics:
  - MAE of 15-min uplift at sensor sites.
  - Brier score for P(uplift > threshold).
  - Interval coverage: the 80% band should contain about 80% of observations.
- Baselines:
  1. **Last comparable cruise day** (the brief's baseline): same number of turnarounds and
     terminals, nearest date.
  2. **Passenger count:** a linear model on total turnaround passengers that day.
  3. **No-cruise median:** predicts no uplift.

**Honest limits:** only roads with sensors are measured. Every other corridor is a model output and
is labelled that way.

**Risk:** judges may see a calibrated simulation as "not AI". Lead with the skill score against the
baselines, and present the product as a probabilistic forecaster learned from data.

## 5. Failures, limits and human control

| Situation | Behaviour |
|---|---|
| Date beyond the published schedule | Refuse: "schedule published to <date>". **Demo this one.** |
| Ship without a passenger figure | Use lower-berth capacity with a wider range, flagged |
| Terminal missing from the gate table, or road outside the network | "Outside coverage", no forecast |
| Schedule collected more than 3 days ago | Stale-data banner |
| Not modelled | Incidents, weather, queue spillback, signal timings, events not in our feeds |

- **Human control:** outputs are suggestions. The officer accepts or edits them and the change is
  logged; nothing changes a sign or signal automatically.
- **Personal data:** none collected.
- **VTS data:** raw VTS pages and CSVs stay out of the repo, because redistribution isn't permitted.

## 6. Data sources

| Source | Used for | Licence | Status |
|---|---|---|---|
| Southampton VTS cruise schedule | Demand | Check terms; keep raw data out of git | To collect |
| OpenStreetMap (osmnx) | Road network, lanes | ODbL | Loader exists (walk) |
| DfT road traffic statistics (AADF by direction) | Background traffic | OGL | To collect |
| National Highways WebTRIS | Calibration and backtest | Check (expected OGL) | Data spike |
| Historic cruise calls 2024–2026 | Backtest | Check per source | Data spike |
| DfT Street Manager open data | Roadworks clashes | Check | Data spike |
| Bus Open Data Service | Optional second check | Check | Data spike |
| Southampton FC fixtures | Clashes | Public; enter by hand | To collect |

## 7. Code changes (after the team agrees)

| Action | Files |
|---|---|
| Keep as is | `data/cruise.py`, `demand/bins.py`, `forecast/montecarlo.py`, `config.py`, `graphs.py` |
| Change | `demand/passengers.py` (share timing curves with vehicles), `routing/pathfinder.py` (candidate-path mode, preloaded background), `evaluate.py` (real dates, corridors), `configs/default.yaml` |
| New | `data/vts.py`, `data/roads.py`, `data/background.py`, `data/observed.py` (WebTRIS or chosen source), `data/clashes.py`, `demand/vehicles.py`, `corridors.py`, `calibrate.py`, `backtest.py`, `app.py` |
| Remove or park on a branch | `data/waterway.py`, `data/tides.py`, `routing/clear_channel.py`, `demand/vessels.py`, `rl/`, `train.py`, `cluster/`, the torch/SB3 extras, the synthetic water scenario |

Dropping torch and SB3 cuts setup from a multi-GB download to a few minutes on any laptop.

## 8. Plan to Sunday 13:00

| When | A: data | B: model | C: evaluation | D: product and pitch |
|---|---|---|---|---|
| Fri 22:30–02:00 | VTS schedule CSV (next 6 weeks + any history); DfT counts | Major-road graph, corridors, gate table, candidate paths | Read the data-spike result; pull the observable's history | Local evidence (council docs, news); plan the council conversation; sketch screens |
| Sat 08:00–13:00 | Street Manager and fixtures for clashes | Vehicle demand + background + assignment → first real forecast for a real date | Observed uplift series + the three baselines | **Talk to council staff**; Streamlit calendar |
| Sat 13:00–20:00 | Freshness, coverage and failure handling | Calibration with Optuna | Backtest table with sample sizes | Day view and what-if |
| Sat 20:00–Sun 02:00 | README data sources table | Integration, end-to-end test | Check the forecast for the demo dates | Business numbers, summary draft, pitch rehearsal |
| Sun 08:00–11:30 | Fixes only | Fixes only | Freeze results | Record the 1–3 min video, 150-word summary |
| Sun 11:30–12:30 | **Submit** (30 min buffer before the 13:00 lock) | | | |

**Business numbers to fill in (D):**
- Running cost per day: CPU minutes and a small VM.
- Setup cost per new city: calibration days.
- The cost of one bad turnaround day: officer time, bus delays, complaints.
- A price that sits well below that cost.

## 9. Decisions for the team

1. Confirm the user and their current cruise-day routine with council staff on Saturday morning.
2. Pick the observed signal once the data spike reports. If nothing gives history, the backtest
   shrinks to this weekend's live data, and the pitch must say so.
3. Delete the waterway and RL code, or park it on a branch.
4. Check the repo creation time with the organisers (initial commit 19:03, hacking opened 20:00).
