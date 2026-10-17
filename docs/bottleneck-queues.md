# Queued traffic waits at its bottleneck (SOT-30)

Written Sat 17 Oct 2026 by [seb-claude] (Claude Code), branch `seb/SOT-30-queue-at-bottleneck`,
stacked on SOT-27 (`docs/west-side-counts.md`). Counts: DfT road traffic statistics, annual
average daily flow 2025 (published June 2026, OGL v3), and the SCC/WSP Portswood counts (July
2024). The learned M271 cruise uplift comes from WebTRIS site 19974 (National Highways, OGL v3)
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

Calibration only (`synthetic_demo.build_ctx()`, deterministic), the same on a laptop and on
Iridis. "Queues only" is steps 1 and 3 (Iridis job 1890524); "this branch" is all four.

| DfT count point (AADF 2025) | Observed | SOT-27 (job 1890271) | Queues only | This branch |
|---|---:|---:|---:|---:|
| 26062 M271, A35 to junction 1 | 53,320 | +11% | +16% | +21% |
| 90217 A33 Redbridge Road | 69,132 | -9% | -7% | -11% |
| 36375 A35 Redbridge Causeway | 61,994 | +34% | +36% | +35% |
| 56347 A33 Millbrook Road West | 49,004 | -38% | -36% | -39% |
| 57434 A33 The Avenue | 27,474 | -25% | -25% | -29% |
| 18312 A335 Thomas Lewis Way | 31,027 | +31% | +33% | +29% |
| 17793 M27 junctions 3-4 | 136,437 | -11% | -10% | -12% |
| 48091 M27 junctions 4-5 | 112,272 | +11% | +9% | +5% |
| 38083 M27 junctions 7-8 | 114,831 | +4% | +3% | 0% |
| 16321 M3 junctions 13-14 | 140,751 | -7% | -8% | -13% |
| Mean absolute error, 10 fitted points | | 18.1% | 18.4% | 19.5% |
| Same without the M271 | | 18.9% | 18.7% | 19.4% |
| Checks: Itchen Bridge / Northam Bridge | 18,300 / 24,312 | +51% / -35% | +55% / -37% | +47% / -40% |

| | SOT-27 | Queues only | This branch |
|---|---:|---:|---:|
| Portswood count sites, weekday AM sum (5,534 counted) | +16% | +16% | +16% |
| Portswood count sites, weekday PM sum (6,549 counted) | -11% | -13% | -13% |
| Scales: county / city / port lorries | 1.00 / 1.42 / 1.75 | 1.00 / 1.43 / 1.75 | 0.92 / 1.36 / 1.75 |
| M271 cruise fit, counted, RMSE per 15 min | 19.6 | 19.3 | **13.6** |
| M271 cruise fit on link load (what the page used), RMSE | 13.8 | | |
| Cruise assumptions the fit picks (car and taxi share, from the county, shift) | x1.0, 80%, 0 | x1.0, 95%, 0 | x1.15, 95%, 0 |
| Corridor-hours at risk per day, 44 days, mean (max) | 110.0 (158.5) | 67.6 (99.4) | IRIDIS_V3 |

The cruise fit compares the paired with-and-without-ships difference on the two M271 northbound
links at WebTRIS 19974 with the learned uplift for a Saturday with 5,000 berths at each dock
(8 sampled days per grid point, 05:00-20:00). Counted, the simulator puts 746 extra vehicles
past the site against 1,104 learned. On the mean cruise day at the chosen assumptions its uplift
starts later (none before 07:00; WebTRIS sees 20-25 per 15 minutes from 06:30), peaks lower
(about 48 per 15 minutes from 08:30 to 10:00 against 69-72) and shows 7-15 per 15 minutes from
13:00 to 15:00 during check-in, when WebTRIS sees about 1.

**The Redbridge Causeway (36375) is at +35%** (SOT-27: +34%). Eastbound, its traffic waits at
the one-lane A35 slip to Redbridge roundabout beyond the count point (on all 921 routes that use
both), so it is counted as it sets off whichever way its queue is handled: the over-supply is
demand (see `docs/west-side-counts.md`), not queues. The M271 rises from +11% to +21% because
it is past those jams: traffic held at the A35 slip and at the A33 slip to Redbridge roundabout
now gets onto it instead of being loaded again upstream (step 1) or disappearing (step 2).

**Corridor-hours at risk fall** because demand over capacity no longer counts waiting traffic on
the links before its bottleneck. Those links were shown at risk only because the same cars were
loaded on them again every 15 minutes.

## Where the cruise cars were lost (before step 2)

On the calibration Saturday (deterministic, averaged over 8 cruise samples, county 95%) the
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
  queues; `demo/bus_check.py` should be rerun after this merges.
- The west side is still over (M271 +21%, Causeway +35%, A335 +29%) and the A33 Millbrook Road
  West and The Avenue under; see `docs/west-side-counts.md`.
- The Portswood AM sum stays at +16%, just outside 15%: the AM and PM sums cannot both be inside
  15% while the fit minimises the log error over both.
