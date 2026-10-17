# Individual vehicles, buses and a PPO decision layer

Two additions to the cruise-day forecast in `demo/`:

1. **Agent-level view.** The model's 15-minute flows turned into individual vehicles for a few
   chosen days, each with an origin, a destination, a purpose, a route and a trajectory along the
   real road links, plus real buses on the same roads (Bluestar and First's X4/X5 from the Bus
   Open Data Service; Unilink is not in BODS).
2. **PPO decision layer.** A reinforcement-learning policy that chooses, every 15 minutes, between
   four levers (metering disembarkation, moving check-in, signs, dock-gate marshals), tested on
   held-out sampled days against doing nothing, a simple rule and the existing ship-timing advisor.

Both run on top of the existing model without changing it: `demo/daysim.py` re-runs one sample of
the forecast exactly as `synthetic_demo.forecast()` draws it, keeping the pieces the forecast adds
up. The test file `tests/test_demo_agents_ppo.py` checks that the pieces add back up to the
model's own matrices and link loads, to the last bit, on a small network.

The PPO results are summarised under [Results](#results-17-oct-2026-iridis-a100); the full generated
tables are [ppo-results.md](ppo-results.md) (run A), [ppo-results-gpu.md](ppo-results-gpu.md)
(run B) and [ppo-results-gpu2.md](ppo-results-gpu2.md) (run C).

## 1. Agents

**What an agent is.** For a chosen day the script draws one sampled day of the forecast (weather,
incident, everyday-traffic noise, driver perception, cruise traffic; the same draws in the same
order as a forecast sample) and allocates it with `traffic_model.run_day`. Agents are then
sampled from what was allocated:

| Kind | Sampled from | Rate (default) |
| --- | --- | --- |
| County commuters, residents (within the area, and working outside), through traffic, county visitors and other county trips, school run | Each purpose's origin-destination flows per 15 minutes; each agent leaves at a random minute of its bin | about 6,000 agents a day, i.e. 1 in about 80 vehicles |
| Match fans | The match demand matrix | same rate |
| Cruise cars (drop-off and pick-up), park and cruise, taxis, coaches | The cruise sampler's own vehicles, with their own minutes and ships (`daysim.cruise_vehicles`, identical draws to `sample_cruise`) | 1 in 4 |

Each agent records how many vehicles it stands for, so the agents added up give the model's
flows back. The page shows that check per kind of trip and per 15 minutes (it differs only by
sampling).

**Route.** One of the model's up to three candidate paths for its origin-destination pair, drawn
with the shares the model gave that pair in the agent's departure bin.

**Trajectory.** The agent drives its path link by link through the day's link loads (`run_day`'s
V/C per edge per bin), using the load of the 15 minutes in which it reaches each link:

- running time = free-flow time / the driver's own speed factor x (1 + 0.15 x min(V/C, 1.5)^4),
  the BPR curve capped as in `traffic_model.delay_minutes`. Each driver keeps their own speed
  factor, drawn once per car: mean 92% of the free-flow speed (the speed limit), 10% of drivers
  below 84%, none above 100% (assumed);
- queuing follows the model's point-queue carry-over: in its first 15 minutes the trip's worst
  link has load x; with probability `CARRY x (1 - 1/x)` the agent does not get through that bin,
  waits at that link and leaves at a random minute of the next bin, and may be held again by the
  same rule (at most two hours).

**Where trips start and end.** The model loads each zone at one node. On the page, a car going
from or to a zone instead starts or ends on a random modelled road within 900 m of the zone's
point (4,811 such points in the 70 zones), joined to the zone's node by the quickest short leg
(free-flow, at most 400 s). Trips from gateways, dock gates, the station and the stadium keep
their own node. About half of all trips start or end on such a street (41-56% per day).

These two changes make the cars look and behave individually, but the cars still do not interact:
a slow driver does not hold up the one behind, and the legs add no traffic to the model. For cars
that interact (car-following, lanes, junctions, queues that spill back), a SUMO microsimulation
fed by the same demand is proposed as separate work.

The page stores each agent's position about every 45 seconds of free-flow driving and at queues,
and draws the agents as dots on a canvas over the map. Click one to see its journey: from, to,
route, departure, arrival, minutes on empty roads, extra minutes in slow traffic and minutes
queuing, and the driver's speed.

**Macro view, same traffic.** In the Vehicles layer the roads are coloured by the same sampled
day, so dots and colours are the same traffic. The other layers stay the average of the forecast's
sampled days.

**The days on the page** are the two with the most cruise traffic added (Sat 24 Oct and Sat 7 Nov,
from the forecast's paired samples) and a term-time weekday without roadworks on Portswood Road
for the bus check (Mon 16 Nov). Each has 7,300 to 9,700 agents. Everyday agents stand for 53 to 89
vehicles each and cruise agents for 4, so cruise traffic is easy to see. Agents times weights match
the model's trips per kind of trip within sampling error (within 3% for the big groups; 16% for
the smallest, outbound commuters on a Saturday).

| Day | Agents | Agents that queue | Median queue, if they queue | 1 in 10 queues longer than |
| --- | --- | --- | --- | --- |
| Sat 24 Oct | 9,748 | 28% | 23 min | 55 min |
| Sat 7 Nov | 9,695 | 13% | 20 min | 47 min |
| Mon 16 Nov | 7,266 | 29% | 23 min | 60 min |

Queues come in 15-minute steps because the model's queue does: a vehicle that does not get
through its bottleneck in one 15-minute bin waits for the next. Cruise vehicles queue about as
often as everyone else; the dock-gate approaches are among the worst bottlenecks around midday.

**Buses.** Routes and timetables come from the Bus Open Data Service GTFS download for the
South West region, which is where Southampton's operators are (downloaded 17 Oct 2026, 297 MB,
Open Government Licence v3.0; recorded in `data/cache/bods/gtfs_south_west.source.json` and on
the page). The South East file has none of them. Of the three operators asked for:

- **Bluestar**: 62 routes with stops in the study area (all city routes, the 6xx school routes,
  PR1 park and ride);
- **First**: only the X4 and X5 Portsmouth expresses ("First Portsmouth, Fareham & Gosport");
- **Unilink**: not in the BODS GTFS at all (neither the South West nor the South East file), so
  it is missing. Its routes would need the operator's own timetable or the OSM fallback.

If BODS cannot be reached the script falls back to OpenStreetMap route=bus relations (ODbL),
which have stops but no timetable, and says so. Each trip's stops are snapped to the model network
(within 250 m) and joined by the quickest free-flow path. Buses run through the same link loads
as the cars, at 80% of a car's free-flow speed, 20 seconds at each stop, waiting at a stop if
early. A bus route is many car trips long, so a bus gets the car's queue rule once per continuous
stretch of links over capacity (one queue), not once per stop. The model has no bus lanes or bus
gates. The page's bus table gives, per route, the extra minutes from traffic by period and the
minutes behind timetable, and for Portswood Road by direction and peak, to hold against the
council's baseline report (Table 3-5: buses ran 0:24 to 4:22 behind timetable in the July 2024
peaks; a quarter of Bluestar 2 southbound buses were 5 or more minutes late).

**What the buses show: the model's queues are too long in places.** On the weekday check day
(Mon 16 Nov, term time, no roadworks on Portswood Road), one sampled day:

| Portswood Road | AM peak: extra min on the road / min behind at the next stop | PM peak |
| --- | --- | --- |
| Bluestar 2 northbound | 7.0 / 6.9 (13 trips) | 18.6 / 16.1 (8) |
| Bluestar 2 southbound | 19.8 / 78 (5) | 10.2 / 118 (10) |
| Bluestar 20 northbound | 1.8 / 3.8 (9) | 6.0 / 7.7 (11) |
| Bluestar 20 southbound | 3.3 / 15.6 (9) | 11.4 / 8.7 (14) |

Only Bluestar 20 northbound in the morning falls inside the council's range. Elsewhere the
modelled delay on Portswood Road alone is 2 to 5 times the observed lateness, and southbound buses
arrive already far behind, from queues further north. On the Saturdays with the Street Manager
permit for signals on Portswood Road (modelled as one lane closed all day) Bluestar 2 runs an hour
or more late. The July counts were out of university term and the model adds 20% for term, but
that does not explain a factor of several. So the macro model's point queues, with capacities
anchored to peak counts, are too long at some bottlenecks, and the cruise forecast's delays there
should be read as high. That is a calibration finding, not a bus result. The fix is in
`traffic_model.py` (queue spill-back, capacities), and it is not part of this work. It has since been
made: capacities and local traffic on the counted roads ([queues.md](queues.md)); the figures here
predate it.

**Limits.**

- Agents are a disaggregation of the macroscopic model, not a microsimulation: they do not
  interact with each other or with signals, and they follow the loads the 15-minute allocation
  gave. A queue holds an agent at its trip's worst link, not at each junction.
- It is one sampled day per date. Another seed gives another day.
- Bus dwell times, the bus speed factor and stop snapping are assumptions; there are no bus
  priority measures.

## 2. PPO decision layer

**Environment** (`demo/ppo_env.py`, Gymnasium). One episode = one sampled day of one date with
ships, drawn as the forecast draws its samples. One step = one 15-minute bin from 05:00 to 20:00
(60 steps), routed with `run_day`'s per-bin logic (`daysim.DaySim`, which reproduces `run_day`
exactly when no lever is used). The observation has the time of day, the day type, school term,
match, wet day, an active incident, roadworks, every corridor's load in the last 15 minutes, and
per terminal the cruise traffic due in the next 30 minutes and the passengers held.

**Levers** (one action per step, a multi-discrete vector):

| Lever | Choices | What it does in the model | Owner |
| --- | --- | --- | --- |
| Disembarkation metering, per terminal | release 100%, 70% or 40% of waiting passengers per 15 minutes | passengers wait in the terminal (never more than 90 minutes); their pick-up cars, taxis, park-and-cruise cars and coaches wait with them | the port (ABP) and the cruise line |
| Check-in opening, per terminal | open 60 or 30 minutes earlier, as planned, or 30 minutes later; closing time unchanged | spreads or bunches drop-offs; chosen once at 05:00 | the cruise line and the port |
| Signs, per sign location (the page's five) | on or off | drivers see that location's corridor links as 30% slower when choosing routes (assumed); travel times do not change | council traffic team |
| Marshals, per dock gate in use | on or off | 25% more capacity on the gate's access links (assumed) | the port, with the council |

**Reward.** Cost per 15 minutes, in pounds, minus the cost of doing nothing on the same sampled
day in the same 15 minutes, divided by 10,000:

| Cost | Value | Basis |
| --- | --- | --- |
| Corridor-hour above 85% of capacity | £5,000 | a weight, not a measured cost: it stands for the risk that a road at its limit locks up, which average delay misses. Chosen so that on a busy day it counts about as much as delay (a busy Saturday has about 110 corridor-hours above 85% and about 57,000 vehicle-hours in queues). The traffic team should set it. |
| Vehicle-hour of delay | £15 | close to an average car value of time per vehicle (assumed). Delay = vehicles the model's point queue carries into the next 15 minutes (each waits 15 minutes) plus slower running of the traffic that gets through each link (the BPR curve, load capped at 1.5). |
| Passenger-hour held in a terminal | £15 | the same value of time per person (assumed) |
| Marshal gate-hour | £120 | four marshals at £30 an hour (assumed) |
| Sign location-hour | £25 | operator time, and a sign left on all day gets ignored (assumed). Added after the first runs, in which signs were free and PPO left them on all day. |

Check-in moves have no cost of their own. Subtracting doing nothing cannot change which policy is
best (no action affects it) but takes most of the day-to-day noise out of the returns.

**Training** (`demo/train_ppo.py train`). Stable-Baselines3 PPO, MLP policy (256, 256), on an
A100 GPU on Iridis. Dates with ships are split: every fourth date (from the third) is held out of
training. Each training episode draws a date and a fresh random sample of that date.

The simulator, not the network, is what takes the time: one 15-minute bin routes 4,796
origin-destination flows over 14,388 candidate routes (three rounds of route choice and queues),
about 45 ms on one CPU core, and every bin is run twice (with the policy and doing nothing). Two
ways to run it:

- one sampled day per CPU core (`ppo_env.CruiseDayEnv` in `SubprocVecEnv`): about 250 steps a
  second on 23 cores;
- `demo/ppo_gpu.py`: 128 sampled days and their do-nothing twins share each sparse matrix product
  on the GPU (PyTorch, float32), while CPU processes draw the next batch of days. On the A100 the
  simulator alone does about 9,500 day-steps a second (38 times the CPU version), and day costs
  match the CPU environment to the penny on the real network (checked on two days, and by a test
  on a small network). In training it runs at about 3,000 steps a second, 12 times the CPU
  version: handing each batch of 128 days (about 170 MB of arrays) from the drawing processes to
  the GPU process is then the limit, with 7 drawing processes or 23. Shared memory instead of
  pickled arrays would be the next step.

**Testing** (`demo/train_ppo.py evaluate`). Four policies on the same sampled days, which were
never used in training (a different random stream), on the held-out dates and on six training
dates:

- **Do nothing.**
- **Rule:** signs at a location when one of its corridors was above 85% of capacity in the last
  15 minutes; marshals at a gate when its access was.
- **Ship-timing advisor:** the page's existing advisor (`synthetic_demo.advise`), which moves each
  ship's disembarkation start and check-in window by coordinate descent, planned for each date from
  the forecast's own samples. It is planned a day ahead and then fixed.
- **PPO**, deterministic.

The generated result files give the mean, the 10th to 90th percentile and the number of sampled
days for corridor-hours above 85%, delay, queuing, passenger-hours held, marshal and sign hours and
total cost, and the paired difference from doing nothing with a 95% bootstrap interval.

### Results (17 Oct 2026, Iridis A100)

All numbers here (agents, buses, PPO) were computed on the model as it was at commit b4a8c0b
(old 8b1e291), before port freight and the cruise assumptions fitted to the M271 reached main. The
code follows both, and the tests pass against them, but the runs have not been repeated on that
model: rerun part 1 and part 2 (Commands) to refresh the figures.

Each policy played the same 260 sampled days: 7 held-out dates and 6 training dates, 20 new
random draws each. Mean per sampled day; the difference is paired against doing nothing on the
same day (95% bootstrap intervals and percentiles in the generated files). Signs were free in
these two runs.

| Policy | Corridor-hours above 85% | Delay (vehicle-hours) | Cost per day | Cheaper than doing nothing |
| --- | --- | --- | --- | --- |
| Do nothing | 75.7 | 65,494 | £1,361,113 | |
| Rule (signs and marshals at 85%) | −0.30 | +648 | +£8,757 | 12% of days |
| Ship-timing advisor | −0.41 | −182 | −£4,774 | 76% of days |
| PPO run A (simulator on CPU cores, 1M steps, 68 min) | −2.31 | +137 | −£7,272 | 84% of days |
| PPO run B (simulator on the GPU, 5M steps, 26 min) | −2.76 | +173 | −£9,769 | 91% of days |

Files: [ppo-results.md](ppo-results.md) (run A, also on the page until run C) and
[ppo-results-gpu.md](ppo-results-gpu.md) (run B). On the held-out dates alone, run B saves
£10,596 a day and 3.1 corridor-hours, about as much as on the training dates, so it is not
memorising dates.

**Where PPO's gain comes from** (run B with one lever switched off at a time, same 260 days,
`train_ppo.py ablation`; standard errors about 0.1 corridor-hours and £500):

| | Corridor-hours | Delay (veh-h) | Cost per day |
| --- | --- | --- | --- |
| PPO, all levers | −2.76 | +173 | −£9,769 |
| without metering | −2.76 | +173 | −£9,782 |
| without its check-in move | −2.79 | +144 | −£10,310 |
| without signs | −1.76 | +26 | −£7,013 |
| without marshals | −0.95 | +194 | −£1,805 |
| marshals-only rule (at 85%, no PPO) | −0.87 | −3 | −£3,861 |

The honest reading:

- **Most of the gain is marshals at the dock gates**, used far more than the rule uses them (12
  gate-hours a day against 4.5, mostly at Dock Gate 4 from about 07:00 to 16:00). That rests on the
  assumed 25% extra gate capacity, which is not measured. A plain marshals-only rule already gets
  40% of PPO's saving.
- **Signs trade delay for corridor-hours**: they push traffic off the signed corridors (fewer
  corridors above 85%) onto longer routes (more delay). That pays only because a corridor-hour is
  weighted at £5,000. The rule's signs do the same and lose money.
- **PPO did not learn useful metering**: it holds almost no passengers.
- **Its check-in move (open 30 minutes later everywhere) slightly hurts**: without it PPO does
  better. PPO picks it at 05:00 and never sees its effect until hours later, a hard credit-
  assignment problem for 60-step episodes.
- **PPO adds delay** compared with doing nothing and with the advisor (which cuts delay by moving
  disembarkation). On delay alone the advisor is better.
- So against the simpler policies, PPO wins on total cost with these weights, but its edge is
  mostly the marshal lever and the corridor-hour weight, not a subtle timing strategy.

**Run C: signs cost £25 an hour** (simulator on the GPU, 8M steps, 133,376 training days, 44
minutes; [ppo-results-gpu2.md](ppo-results-gpu2.md)). Run B left signs on all day because they
were free, so the page's plan read "signs 05:00–18:00". With a stated sign cost (costs below now
include it, which also makes the rule slightly worse):

| Policy | Corridor-hours above 85% | Delay (vehicle-hours) | Cost per day | Cheaper than doing nothing |
| --- | --- | --- | --- | --- |
| Rule | −0.30 | +648 | +£9,298 | 12% of days |
| Ship-timing advisor | −0.41 | −182 | −£4,774 | 76% of days |
| PPO run C | −2.90 | +136 | −£10,724 | 93% of days |
| PPO run C, held-out dates only | −3.19 | +154 | −£11,864 | 94% of days |

Run C is the best of the three runs on corridor-hours and cost, with fewer marshal hours (9.7 a
day against 12) and about the same sign hours (21 against 24: at £25 an hour signs still pay when
a corridor-hour is weighted at £5,000). Its ablation tells the same story as run B's: without
marshals it saves £2,408 a day, without signs £7,722, without metering or its check-in moves about
the same as with them. The page shows run C, with the ablation under its test table.

Its plan on the page is shown as windows of at least 30 minutes, joining gaps of 15 minutes
(`train_ppo.py rewindow`): the policy itself switches signs on and off from one 15 minutes to the
next, which no operator would follow. The per-bin shares behind the windows are in the results
JSON.

**On the page.** The page shows run C, chosen before testing as the longest-trained policy under
the final costs. For the days with agents it is run on eight more sampled days and turned into
actions with times (a lever is recommended in the 15 minutes where PPO used it on at least half of
those days; metering only while passengers are waiting), each with its owner and Approve / Decline
buttons. Nothing is applied automatically: the port and the cruise lines own disembarkation and
check-in, the council owns the signs, and the port runs the gates. Under the test table the page
shows the ablation, so the marshal caveat sits next to the numbers.

**Limits.**

- PPO optimises the model, so it learns the model's weak spots as readily as real effects. The
  effect sizes of signs (30%) and marshals (25%) are assumptions, not measured.
- Metering holds pick-up drivers with their passengers; in reality some would arrive and wait at
  the gate.
- The levers differ between policies: the advisor moves disembarkation starts by up to 2.5 hours,
  which PPO cannot; PPO meters and uses signs and marshals, which the advisor cannot.
- Costs are stated weights, and different weights give a different best policy.
- Not tested: PPO together with the advisor's disembarkation moves, or PPO trained with the
  advisor's lever. The check-in choice made once at 05:00 is hard for PPO to learn from; a
  separate day-ahead planner (like the advisor) suits it better.
- The agents' and buses' queue waits, and PPO's savings, inherit the macro model's queues, which
  the bus check suggests are too long at some bottlenecks.

## Commands

All on Iridis (`cluster/iridis/`), since the full runs need many cores:

```bash
bash cluster/iridis/demo_env.sh
```

```bash
sbatch cluster/iridis/agents_ppo_smoke.slurm
```

```bash
J=$(sbatch --parsable cluster/iridis/agents_ppo_cpu.slurm); sbatch --dependency=afterok:$J cluster/iridis/agents_ppo_gpu.slurm
```

With the simulator on the GPU (part 2 with `GPU_ENVS`; `TAG` keeps the default results):

```bash
GPU_ENVS=128 TIMESTEPS=8000000 TAG=gpu2 sbatch cluster/iridis/agents_ppo_gpu.slurm
```

Ablation of a trained policy (one lever off at a time) and the page with a chosen run:

```bash
.venv-demo/bin/python demo/train_ppo.py ablation --model runs/ppo/<job>/model.zip --json demo/out/ppo_ablation.json
```

```bash
.venv-demo/bin/python demo/page_extras.py --template demo/page.html --ppo demo/out/ppo_gpu2.json --ablation demo/out/ppo_ablation.json
```

Part 1 (CPU) builds the forecast page, reduces the bus timetable, simulates the agents and buses
(`demo/agents.py`) and caches the warm-start route shares. Part 2 (A100) trains PPO, tests it,
writes `demo/out/ppo.json` and `docs/ppo-results.md`, and puts agents, buses and PPO into the
page (`demo/page_extras.py`, which thins agents if the page would pass 15.5 MB).

Locally, with the same environment as the demo plus `gymnasium`, `stable-baselines3` and `torch`:

```bash
uv run --no-project --python 3.12 --with numpy --with scipy --with networkx --with pandas --with shapely --with pyproj --with gymnasium --with stable-baselines3 --with torch python demo/train_ppo.py train --n-envs 8
```

Tests: `uv run --with scipy --with shapely pytest tests/test_demo_agents_ppo.py`.
