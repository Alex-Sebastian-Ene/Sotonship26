# Queued traffic waits at its bottleneck (SOT-30)

Written Sat 17 Oct 2026 by [seb-claude] (Claude Code), branch `seb/SOT-30-queue-at-bottleneck`,
on main 3b32541, which has SOT-27 merged (`docs/west-side-counts.md`, `docs/queues.md`). Counts: DfT
road traffic statistics, annual average daily flow 2025 (published June 2026, OGL v3), and the
SCC/WSP Portswood counts and Bluestar run times (July 2024; Portswood Project Baseline Data
Report, Jan 2025, Table 3-5). The learned M271 cruise uplift comes from WebTRIS site 19974 (National Highways, OGL v3)
through `demo/webtris_backtest.py`. Every other number here is the city simulator
(`demo/traffic_model.py`), not an observation.

## What was wrong

`run_day` routes each 15 minutes in turn. Traffic that could not get past its route's
bottleneck went back into its origin-destination demand (`veh = D[b] + queue`) and was routed
again over the whole route the next 15 minutes. So for every 15 minutes it waited, it took up
the capacity of every link it had already passed, upstream of the jam, and raised demand over
capacity (`x`) there. On one weekday with SOT-27's calibration the network had 6,399 link-bins
over capacity this way, and 3,509 once the queue stays where it is.

Counting each vehicle once (SOT-27) did not fix the M271 cruise fit, because queued traffic
still re-occupied the slip roads at Redbridge every 15 minutes, and extra cruise cars mostly
pushed other traffic out of them.

## The change

1. **Queues sit at the bottleneck** (`traffic_model.Queues`, used by `run_day`, `daysim.DaySim`
   and `ppo_gpu.py`). Each route's waiting traffic is kept at the link where it waits: the first
   link where the route's demand over capacity is highest. The next 15 minutes it loads that
   link and the links after it, and it is not routed again. New trips still choose a route
   (logit on perceived times), and they see the queue's load on the roads (through
   `equilibrium_bin`'s `pre`). Queued traffic meets the worst link ahead of it, which can be
   further on than where it waits; it moves there if it gets past the first one.
2. **The share that leaves a queue is counted as getting through.** `CARRY = 0.8` is "the share
   of traffic stuck in a queue that is still waiting 15 minutes later". The other 20% used to
   disappear: a counter after the bottleneck never saw it. Now it is counted on the bottleneck
   and the links after it in the same 15 minutes, so every vehicle passes every link of its
   route once (unless it is still waiting at 20:00). Queues and `x` are the same as in step 1;
   only `count` and `cruise_count` change.
3. **The M271 cruise probe uses `count`** (what WebTRIS 19974 counts, each vehicle once and at
   most capacity) instead of link load. `synthetic_demo.forecast()`.
4. **A finer last step for the city scale** in `build_ctx` (grid 0.9 to 1.1 of the current
   scale). The council-count grid steps by about 15%, and with step 2 the scale landed a step
   off (Portswood AM +20%).

Every `run_day` output still works: `x`, `count`, `cruise_count`, `cruise_edge`, `cruise_path`,
`queue`, `held`, `path`, `time`, `delay`. `cruise_path` is now the cruise traffic setting off on
each route, so summed over the day it counts each car once. Only routes through a link over
capacity, or with a queue, are looked at in a bin, so a day runs no slower than before: on one
weekday (3 iterations, laptop) `x` alone took 0.67 s against 0.80 s, and `x` with `count`
1.23 s against 2.17 s.

## Results

Calibration only (`synthetic_demo.build_ctx()`) is deterministic and the same on a laptop and on
Iridis. "SOT-27" is main before this branch: Iridis jobs 1890804 (fits) and 1891089 (page and
bus check, `/scratch/ase1g23/sotonship26-sot27c`, `COUNT_HEADROOM` 1.3). "Queues only" is steps
1, 3 and 4 without step 2 (laptop). "This branch" is all four: Iridis job 1891526
(`/scratch/ase1g23/sotonship26-sot30c`, `cluster/iridis/bus_check.slurm`, which builds the page
and then runs the bus check).

| DfT count point (AADF 2025) | Observed | SOT-27 | Queues only | This branch |
|---|---:|---:|---:|---:|
| 26062 M271, A35 to junction 1 | 53,320 | +10% | +15% | +24% |
| 90217 A33 Redbridge Road | 69,132 | -10% | -9% | -8% |
| 36375 A35 Redbridge Causeway | 61,994 | +34% | +37% | +40% |
| 56347 A33 Millbrook Road West | 49,004 | -38% | -37% | -37% |
| 57434 A33 The Avenue | 27,474 | -26% | -26% | -27% |
| 18312 A335 Thomas Lewis Way | 31,027 | +31% | +32% | +34% |
| 17793 M27 junctions 3-4 | 136,437 | -12% | -11% | -7% |
| 48091 M27 junctions 4-5 | 112,272 | +11% | +9% | +13% |
| 38083 M27 junctions 7-8 | 114,831 | +4% | +3% | +7% |
| 16321 M3 junctions 13-14 | 140,751 | -7% | -9% | -7% |
| Mean absolute error, 10 fitted points | | 18.3% | 18.6% | 20.4% |
| Same without the M271 | | | 19.1% | 20.0% |
| Checks: Itchen Bridge / Northam Bridge | 18,300 / 24,312 | +51% / -35% | +55% / -37% | +53% / -38% |

| | SOT-27 | Queues only | This branch |
|---|---:|---:|---:|
| Portswood count sites, weekday AM sum (5,534 counted) | +16% | +16% | +16% |
| Portswood count sites, weekday PM sum (6,549 counted) | -11% | -13% | -13% |
| Scales: county / city / port lorries | 1.00 / 1.42 / 1.30 | 1.00 / 1.43 / 1.30 | 1.00 / 1.36 / 1.30 |
| M271 cruise fit, counted, RMSE per 15 min | 19.6 | 18.4 | **13.7** |
| M271 cruise fit on link load (what the page used), RMSE | 13.7 | | |
| Cruise assumptions the fit picks (car and taxi share, from the county, shift) | x1.0, 80%, 0 | x1.0, 95%, 0 | x1.15, 95%, 0 |
| Corridor-hours at risk per day, 44 days, with ships (without) | 91.8 (88.4) | | **48.6 (46.1)** |
| Cruise uplift on ship days, corridor-hours (29 days) | 5.13 | | 3.79 |
| Portswood bus run times, July-like weekday, RMSE against Table 3-5, all 8 figures | 2.88 min | | **2.13 min** |
| Same without Bluestar 20 northbound | 1.21 min | | 2.16 min |
| Page calendar, ship days Minor / Moderate / Heavy / Severe | 4 / 12 / 10 / 3 | | 7 / 12 / 10 / 0 |

The cruise fit compares the paired with-and-without-ships difference on the two M271 northbound
links at WebTRIS 19974 with the learned uplift for a Saturday with 5,000 berths at each dock
(8 sampled days per grid point, 05:00-20:00). Counted, the simulator puts 746 extra vehicles
past the site against 1,104 learned. On the mean cruise day at the chosen assumptions its uplift
starts later (none before 07:00; WebTRIS sees 20-25 per 15 minutes from 06:30), peaks lower
(about 48 per 15 minutes from 08:30 to 10:00 against 69-72) and shows 7-15 per 15 minutes from
13:00 to 15:00 during check-in, when WebTRIS sees about 1.

**Step 2 is a trade.** It is what brings the counted cruise fit under 14 (18.4 without it), and
it costs about 2 points of DfT error: the 20% of each queue it counts as getting through lands on
the west side, which is already over. **The Redbridge Causeway (36375) is at +40%** (SOT-27:
+34%). Eastbound its traffic waits at the one-lane A35 slip to Redbridge roundabout beyond the
count point (on all 921 routes that use both), so it is counted as it sets off and the queue
change does not touch it. Westbound the count point is past Redbridge roundabout, so traffic
that used to be loaded again upstream (step 1) or to disappear (step 2) now reaches it. The
M271 (+24%) is past the same jams.

**Portswood bus run times** (`demo/bus_check.py`, 16 sampled days of Mon 16 Nov without the
university-term uplift, like the council's July survey; RMSE over the AM and PM figures of
Bluestar 2 and 20 in both directions) go from 2.88 to 2.13 minutes over all eight figures.
Bluestar 20 northbound, the one SOT-27 could not fit (+6.9 minutes in the AM), comes to +2.8;
the others now run 1.5-4 minutes quicker than the council measured (20 southbound -2.5 / -3.9),
so without 20 northbound the error rises from 1.21 to 2.16. `COUNT_HEADROOM` (1.3) was fitted
with the old queues, which loaded queued traffic on Portswood Road again every 15 minutes; with
that gone the road has more room than the counts suggest. Refitting it is a follow-up.

**Corridor-hours at risk fall by about half** (91.8 to 48.6) because demand over capacity no longer counts
waiting traffic on the links before its bottleneck; those links were shown at risk only because
the same cars were loaded on them again every 15 minutes. On the previous SOT-27 tip (c3817fc,
before the lorry limit) the same change took the mean from 110.0 to 57.9 (Iridis jobs 1890271 and
1890911): each day fell to 0.41-0.63 of its old value, the order of days barely changed
(Spearman rank correlation 0.85), and Fri 27 Nov stayed the worst day. The page's risk numbers
change with it. Its calendar bands are fixed amounts of congestion the ships add (Moderate from
1.5, Heavy from 5, Severe from 10 road-hours), and the ships' share falls from 5.1 to 3.8
road-hours on an average ship day, so no day is Severe any more and three more are Minor. Its
action triggers are probabilities (marshals where the ships add 40 points of risk at a gate,
signs at 50): marshals are still advised on 20 of 29 ship days, signs on 5 instead of 2.

## Where the cruise cars were lost (before step 2)

On the calibration Saturday (deterministic, averaged over 8 cruise samples, county 95%, on the
previous SOT-27 tip c3817fc) the
ships put 938 cars on routes over the M271 probe; 655 were counted there and the paired
difference was 465. They were held at Central Road inside the Western Docks (800 veh/h, demand
over capacity 2.2 with ships, 0.8 without) and at the one-lane A33 slip down to Redbridge
roundabout (link 955, over capacity 29 bins on a Saturday without ships, 38 with). At both, 20%
of the waiting traffic vanished every 15 minutes, and other traffic held behind the cruise
cars vanished too. On that deterministic day, doubling the dock roads' and that slip's capacity
only took the error from 18.9 to 17.0. Counting the 20% as getting through took it to 15.5 at
the same assumptions and 14.1 at the best grid point (x1.15, 95%, no shift).

## Not changed / follow-ups

- **The PPO policy** in `models/` (Iridis run 1889084) was trained on the old queues.
  `daysim.DaySim` and `ppo_gpu.py` now use the new ones (their tests pass), so the policy should
  be retrained before its numbers are quoted.
- **`COUNT_HEADROOM`** (main, d62d7e7) was fitted to the Portswood bus run times with the old
  queues (1.15, then 1.3 in SOT-27); on the new ones Portswood buses run quicker than counted, so
  it should be refitted.
- The west side is still over (M271 +24%, Causeway +40%, A335 +34%) and the A33 Millbrook Road
  West and The Avenue under; see `docs/west-side-counts.md`.
- The Portswood AM sum stays at +16%, just outside 15%: the AM and PM sums cannot both be inside
  15% while the fit minimises the log error over both.
