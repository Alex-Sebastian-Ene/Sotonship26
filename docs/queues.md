# Queues at bottlenecks: the Portswood Road bus check

Sat 17 Oct 2026. The agents work ([agents-and-ppo.md](agents-and-ppo.md)) ran Bluestar buses through
the model's link loads and found them 2 to 5 times later on Portswood Road than the council
measured. This note finds why, changes `demo/traffic_model.py`, and gives the numbers before and
after.

**The change (in `anchor_counts`).** The counted roads (Portswood Road, Highfield Lane, Bevois
Hill) took their July 2024 peak-hour count as their capacity. That count is what the roads
carried, not what they can carry, so capacity is now the count times `COUNT_HEADROOM` = 1.15. The
July peak hour then runs at about 92% of capacity. Local traffic is now also added link by link,
up to the count, instead of adding the middle link's shortfall to every link, which pushed the
busier links well past their capacity. On a July-like weekday, modelled Bluestar 2 and 20 run
times on Portswood Road now match the council's within 1.7 minutes (root-mean-square over the
eight peak figures), down from 4.5. Corridor-hours at risk fall from 76.6 to 71.5 a day, 4.4 of
the 5.1 on Portswood Road and Highfield Lane. The cruise uplift (5.7 corridor-hours on ship
days) and the DfT and council count fits do not change.

Refitted after SOT-27 (count-once flows, new city and county scales): `COUNT_HEADROOM` = 1.3 (July
peak hour at 81% of capacity), and roads the zones already fill (Highfield Lane, St Denys Road)
keep road-class capacity; see [Refit after SOT-27](#refit-after-sot-27).

## The check

`demo/bus_check.py` runs every Bluestar 2 and 20 trip from the Bus Open Data Service timetable
(GTFS, South West, downloaded 17 Oct 2026) through the link loads of one sampled day. It uses
`buses.run_bus`, the rule the agents page uses: 80% of car free-flow speed, 20 seconds per stop,
no early departures, and one chance of being held per stretch of links over capacity. It
measures the same thing as the council's table: the run time from the last stop before Portswood
Road to the first stop after it, minus the timetabled time between those stops. It averages 16
sampled days, because one day is noisy (weather, incidents, everyday traffic).

The council's figures are from Southampton City Council / WSP, *Portswood Project Baseline Data
Report*, January 2025, Table 3-5: weekday bus run times on Portswood Road, 1-14 July 2024.

| Service, weekday | Minutes behind timetable, AM peak 07-10 | PM peak 16-19 | Share 5+ min slower (all day) |
| --- | --- | --- | --- |
| Bluestar 2 northbound (S-N) | 0:53 | 1:08 | 2.3% |
| Bluestar 2 southbound (N-S) | 4:22 | 4:10 | 25.1% |
| Bluestar 20 northbound | -0:10 | 1:47 | 2.4% |
| Bluestar 20 southbound | 0:23 | 1:10 | 3.3% |

July was school term but not university term, so the check runs three days:

- **July-like**: Mon 16 Nov with local traffic built without the university-term uplift
  (`--uni-term 1`). This compares like with like.
- **Term**: Mon 16 Nov as forecast. This is a term-time weekday with no roadworks on Portswood
  Road, and the model adds `UNI_TERM` = 20% local traffic on the counted roads.
- **Permit day**: Wed 21 Oct, with the two Street Manager permits for signals on Portswood Road.

All runs were on Iridis (`cluster/iridis/bus_check.slurm`). Each run builds the forecast page (30
paired samples a day, 44 days), runs the three bus checks, and prints everything with
`demo/queue_report.py`.

## What was wrong

Before the change, on the term day the worst Portswood Road link ran at 2.3 to 3.1 times capacity
southbound and 1.4 to 2.1 northbound in every peak hour. Capacity was about 370 veh/h a direction,
after wet days. Two things in `anchor_counts` caused this:

1. **Capacity was set to the count.** The rule took the busier peak hour, 0.95 times the 3-hour
   count divided by 3 and times 1.15, as the road's limit. Its stated reason was that "measured
   peak speeds of 16-20 mph show they are at their limit". But the same report's Table 3-10 gives
   all-day average speeds at those sites at most 2 mph above the peak ones (the morning peak is
   often the faster). On Portswood Road
   the peaks average 21.1 mph northbound in the morning and 18.6 mph in the evening, against 19.6
   mph all day. Low speeds are the high street's normal state, not a queue. A road at its limit
   for three hours would also not keep buses within 0 to 4 minutes of timetable. With demand at
   the count, or 1.2 times it in term time, and capacity at about the count, the point queue never
   clears. With `CARRY` = 0.8 it settles at four bins' worth of the excess, so V/C goes towards 2.
2. **Local traffic was added uniformly.** `pre` added the middle link's shortfall to every link
   of a direction. Links near the Portswood junction carry about 700 veh/h of routed traffic
   southbound, against 300 to 400 on the rest. They got the same 300 to 360 veh/h on top and ran
   at 2.5 to 2.7 times capacity even in a deterministic day.

## Causes, tested one at a time

Each variant was tested on the calibrated model with the counted roads rebuilt under that
variant. The bus check used 12 sampled days, or 32 where marked, and the corridor-hours used 8
paired samples per date. The fit column is the root-mean-square difference from the council's
eight peak figures on the July-like day.

| Variant | Fit, min | Bluestar 2 SB, July-like AM/PM | Same, term day | Corridor-h with ships | Portswood Road h |
| --- | --- | --- | --- | --- | --- |
| As it was | 4.53 | 8.1 / 14.5 | 13.5 / 16.3 | 78.5 | 13.5 |
| (1) Wait the point queue's mean, not a whole bin | 7.29 | 13.3 / 20.7 | 16.1 / 23.6 | 78.5 | 13.5 |
| No university-term uplift | 4.53 | 8.1 / 14.5 | 8.1 / 14.5 | 75.7 | 13.3 |
| (2a) Local traffic per link | 2.51 (32) | 4.0 / 8.9 | 6.2 / 11.5 | 76.5 | 12.1 |
| (2b) Capacity x1.25 | 2.98 | 6.0 / 11.6 | 8.0 / 12.4 | 74.0 | 13.0 |
| (2b) Capacity x1.5 | 1.51 | 4.0 / 5.2 | 1.6 / 6.6 | 70.6 | 12.4 |
| (2) Per link + capacity x1.1 | 1.77 (32) | 5.5 / 5.1 | 5.1 / 8.9 | 74.5 | 11.7 |
| **(2) Per link + capacity x1.15** | **1.78 (32)** | 3.9 / 5.9 | 2.8 / 7.1 | 73.5 | 11.4 |
| (2) Per link + capacity x1.2 | 1.96 (32) | 1.7 / 4.1 | 0.7 / 5.5 | 72.5 | 11.2 |
| (2) Per link + capacity x1.35 | 2.40 | -0.4 / 3.2 | 1.9 / 2.4 | 69.2 | 9.8 |
| (2) Per link + capacity x1.5 | 2.58 | 0.7 / 0.9 | -0.8 / 1.2 | 66.2 | 8.2 |
| (2) Per link + capacity x2 | 3.44 | -0.7 / -2.0 | -0.5 / -2.0 | 59.2 | 3.7 |
| (2) Road-class capacity (1,000 veh/h a lane) | 3.60 | -1.5 / -1.9 | 0.1 / -0.9 | 61.3 | 6.8 |
| Council, July 2024 |  | 4.4 / 4.2 |  |  |  |

- **(1) A vehicle not served in a 15-minute bin waits a whole bin at its trip's worst link.**
  This is not why delays are long. A bus is held with chance 0.8 (1 - 1/x), for about 15
  minutes. The deterministic point-queue wait at the same load, 0.8 (x - 1) times 15 minutes, is
  longer on average (fit 7.29), and it makes every bus late rather than some. The whole-bin rule
  spreads the delay over fewer buses, but it does not lengthen it. The problem is x. Left as it
  is.
- **(2) Capacity on the counted roads, set from peak-hour counts, is too low.** This is the
  cause. Per-link local traffic halves the misfit. With it, the fit is flat between 1.1 and 1.2
  times the count (32 sampled days each) and worse on either side. Capacity x1.5 alone fits about
  as well, but without per-link local traffic Portswood Road then carries 15-19% more than the
  count (2,401 and 3,045 vehicles in the peaks against 2,021 and 2,637). So both parts are
  needed. Taking the middle of the flat range, 1.15, puts the July peak hour at V/C 0.92. That is
  consistent with Table 3-10's small drop in speed at the peaks. Above 1.35, Bluestar 2
  southbound runs early in the peaks, which the council's 25% of buses 5+ minutes late rules
  out.
- **The university-term uplift alone** does nothing to the July-like misfit, which by definition
  has no uplift. It is kept: the term day should be somewhat worse than July.
- **(3) A permit closes a lane for all of 05:00-20:00.** This only matters on permit days. Before
  the capacity change, on Wed 21 Oct, Bluestar 2 southbound ran 20.2 / 32.3 minutes behind with
  the lane closed all day. It ran 10.7 / 18.2 with the closure only 09:30-15:30, and 9.8 / 15.0
  with no closure. So the all-day closure accounts for about half of that day's delay. Left as
  it is: permit LP709S30000746-02 (19-30 Oct) gives "two-way signals, daytime" with no hours.
  Signals often stay over an open excavation, and it overlaps every day of the timed permit
  (20-23 Oct, 09:30-15:30). Applying hours only where a permit states them would
  change no day in the window.

## Before and after

Before is `origin/main` at 322fa2e (Iridis job 1889803). After is this branch (job 1890098), with
the same inputs and settings.

**Buses on Portswood Road**, minutes different to the timetable, AM / PM peak, 16 sampled days:

| Service | Council, July 2024 | July-like, before | July-like, after | Term day, before | Term day, after | Permit day, before | Permit day, after |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Bluestar 2 northbound | 0.9 / 1.1 | 4.1 / 6.4 | 0.5 / 0.6 | 5.0 / 9.2 | 0.6 / 2.3 | 14.7 / 14.3 | 3.8 / 13.9 |
| Bluestar 2 southbound | 4.4 / 4.2 | 8.5 / 13.6 | 3.0 / 5.4 | 11.2 / 18.5 | 2.6 / 7.1 | 21.1 / 32.3 | 13.2 / 17.1 |
| Bluestar 20 northbound | -0.2 / 1.8 | 2.4 / 4.2 | 2.4 / 3.2 | 3.0 / 5.9 | 2.2 / 4.5 | 5.3 / 11.2 | 3.6 / 10.0 |
| Bluestar 20 southbound | 0.4 / 1.2 | -0.9 / 2.8 | -1.7 / -1.4 | 0.3 / 5.2 | -1.6 / 1.2 | 8.7 / 16.0 | 4.6 / 10.4 |
| Fit to the council, min |  | 4.48 | 1.72 |  |  |  |  |

Share of buses 5 or more minutes slower than timetabled, whole day, for Bluestar 2 NB / 2 SB / 20
NB / 20 SB:

| Council | July-like, before | July-like, after | Term day, before | Term day, after |
| --- | --- | --- | --- | --- |
| 2% / 25% / 2% / 3% | 19% / 32% / 6% / 15% | 4% / 12% / 2% / 2% | 26% / 39% / 12% / 23% | 8% / 17% / 5% / 8% |

On the term day the model is now within -2 to +3 minutes of the council's July figures, mostly
above, as expected with 20% more local traffic. Before, it was up to 14 minutes above. The worst
Portswood Road link in the peaks went from V/C 2.3-3.1 to 1.2-1.8 southbound, and from 1.4-2.1 to
0.8-1.3 northbound.

**Corridor-hours at risk** (V/C over 0.85, expected hours a day summed over corridors, mean over
the 44 forecast days):

| | Before | After |
| --- | --- | --- |
| With ships | 76.6 | 71.5 |
| Without ships | 72.8 | 67.7 |
| Cruise uplift on ship days | 5.69 | 5.73 |
| Portswood Road | 13.45 | 11.40 |
| Highfield Lane | 9.72 | 7.39 |
| Every other corridor | | within 0.2 h of before (St Denys Road -0.2, The Avenue -0.1) |
| Mon 16 Nov, with / without ships | 99.4 / 92.1 | 95.7 / 88.3 |
| Sat 24 Oct | 68.6 / 50.0 | 64.2 / 45.5 |
| Sat 7 Nov | 66.6 / 49.4 | 60.8 / 43.6 |

**Count fits.** `calibrate_external` (DfT AADF, log error 0.315) and `calibrate_to_counts` (council
counts, log error 0.12 on site totals) are unchanged. Both run before `anchor_counts`, so this
change cannot move them, and the build logs confirm it. On the counted roads themselves, flows
now match the counts better. These are served two-way flows on a deterministic term weekday
against the counts times 1.2, as the 80th-percentile link in `calibrate_to_counts`:

| Road, period | Counts x1.2 | Before | After |
| --- | --- | --- | --- |
| Portswood Road 07-10 | 2,021 | 2,182 (+8%) | 2,012 (0%) |
| Portswood Road 16-19 | 2,637 | 2,394 (-9%) | 2,587 (-2%) |
| Highfield Lane 07-10 | 1,720 | 1,822 (+6%) | 1,842 (+7%) |
| Highfield Lane 16-19 | 1,802 | 1,928 (+7%) | 1,890 (+5%) |
| Bevois Hill 07-10 / 16-19 | 1,228 / 1,591 | 1,229 / 1,591 | 1,226 / 1,588 |

## Refit after SOT-27

SOT-27 (`docs/west-side-counts.md`) counts each vehicle once in the count fits and mends the west
side of the network, which raised the city scale from x0.95 to x1.42 and the county scale from
x0.80 to x1.00. On that build the bus fit no longer held (Iridis job 1890804): Highfield Lane's
zone traffic alone was 1.08 times its count, so its count-based capacity (the 350 veh/h floor
x1.15) built a jam its July speeds do not show (Table 3-10: 24.5/24.9 mph AM, 21.0/24.5 PM).

Refit by the queues session on a copy of that build, July-like Mon 16 Nov, 32 sampled days. Model
minus timetable, minutes, AM / PM; the council's figures are in the first row:

| Variant | B2 NB | B2 SB | B20 NB | B20 SB | Fit, all 8 | Fit without B20 NB | Corridor-hours |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Council, July 2024 | 0.9 / 1.1 | 4.4 / 4.2 | -0.2 / 1.8 | 0.4 / 1.2 | | | |
| SOT-27 as built, x1.15 (job 1890804, 16 days) | 2.3 / 2.6 | 5.4 / 8.2 | 5.8 / 7.8 | -0.6 / 0.0 | 3.46 | 1.99 | 102.8 |
| x1.3 | 0.8 / 2.5 | 3.1 / 6.1 | 6.3 / 5.4 | -0.4 / -1.7 | 2.97 | 1.65 | 102.4 |
| x1.5 | 0.2 / 0.0 | 1.7 / 3.8 | 5.2 / 5.4 | -0.7 / -1.5 | 2.74 | 1.71 | 99.1 |
| x1.75 | -0.3 / -0.9 | 1.3 / 0.9 | 5.6 / 4.8 | -0.2 / -1.6 | 3.07 | 2.38 | 94.9 |
| x2 | -0.6 / -1.6 | 0.6 / 0.0 | 5.8 / 4.5 | -0.4 / -1.2 | 3.36 | | 91.4 |
| road-class capacity | -0.7 / -2.0 | -0.6 / -1.6 | 5.9 / 3.9 | -0.3 / -1.3 | 3.83 | | 85.0 |
| skip roads the zones already fill, x1.15 | 2.1 / 2.7 | 5.3 / 7.9 | 7.1 / 7.2 | -0.2 / -0.7 | 3.62 | 1.94 | 94.6 |
| **skip roads the zones already fill, x1.3** | 0.7 / 1.1 | 4.4 / 5.4 | 6.8 / 5.2 | -0.6 / -0.5 | 2.86 | **0.95** | 93.6 |

Adopted: `COUNT_HEADROOM` = 1.3 (was 1.15), and `anchor_counts` leaves a road at road-class
capacity where the zones alone already carry at least its count (was more than 1.5 times). On
SOT-27 that is Highfield Lane and St Denys Road.

The full rebuild with the refit (Iridis job 1891089, `bus_check.slurm`, 16 sampled days), against
SOT-27 as built (job 1890804):

| | As built | Refit |
| --- | --- | --- |
| July-like fit, all 8 | 3.46 | 2.88 |
| July-like fit without B20 NB | 1.99 | 1.20 |
| B2 NB / B2 SB, AM / PM | 2.3 / 2.6, 5.4 / 8.2 | 0.4 / 0.7, 4.9 / 6.7 |
| B20 NB / B20 SB, AM / PM | 5.8 / 7.8, -0.6 / 0.0 | 6.7 / 5.0, -0.3 / 0.1 |
| Corridor-hours at risk with / without ships | 102.8 / 99.4 | 91.8 / 88.4 |
| Highfield Lane corridor-hours | 10.52 | 0.24 |
| Portswood Road corridor-hours | 11.72 | 10.92 |

Served flows on the counted roads are within 1% of the counts x1.2 on Portswood Road and Bevois
Hill, and +3% to +16% on Highfield Lane. The DfT, lorry and cruise fits run before
`anchor_counts` and are unchanged (M271 cruise fit RMSE 13.7).

**Bluestar 20 northbound** is 5 to 7 minutes behind at every capacity, even road class, so it is
not the headroom. Its section in `bus_check` runs between its Portswood Road stops via St Denys
Road, The Triangle and Thomas Lewis Way, where the links run at V/C 1.31 AM / 1.15 PM at
road-class capacity, with St Denys Road served at 2.5 times its count. That comes from the city
scale, which `calibrate_to_counts` fits to the sum over the four roads: Portswood Road and Bevois
Hill, where the zones carry only 0.2 to 0.6 times the count before `anchor_counts` tops them up,
pull it up. Fitting the scale on Highfield Lane and St Denys Road alone (job 1891090) gave a city
scale of x0.33 and a county scale of x1.46. Bluestar 20 northbound improved (3.2 / 5.4), but the
DfT error rose from 18.3% to 27.1% (M27 +39% to +43%) and the cruise fit from 13.7 to 15.2, so it
was not adopted.

## Limits

- The headroom is fitted to the same Table 3-5 the check compares against. It is one number for
  three roads, and the term day and permit day are not fitted. Observed term-time lateness would
  be the real test. `scripts/bustimes.py` (on main) can collect it from the weekday peaks from
  Mon 19 Oct, though Portswood Road has works 19-30 Oct.
- Bluestar 20 northbound is about 2.4 minutes behind in the morning at every capacity, even with
  no queue. That comes from the timetable against the assumed bus speed and dwell, not from
  traffic. The council's Bluestar 2 southbound section starts at Stag Gates and includes Lodge
  Road, while the model's section is the stops either side of Portswood Road. This may be why
  the model's 5+ minute share for that service (12%) is below the council's 25%.
- One short Portswood Road link near the junction still gets about 700 veh/h of routed traffic
  southbound and runs over capacity in the peaks. That is where zone traffic converges in the
  model, and this change does not touch route choice.
- Only the counted roads change. Other bottlenecks (dock-gate approaches, the M271) have no bus or
  speed data in this check. The M271 / A35 over-prediction fix (SOT-27) changed `flows()`, which
  `anchor_counts` uses, and the demand; the headroom was refitted for it (above).
- The agent, bus and PPO figures in [agents-and-ppo.md](agents-and-ppo.md) were computed before
  this change, and their queue waits will be shorter on the new model.

## Commands

On Iridis, from a checkout with the cached inputs (see `cluster/iridis/agents_ppo_cpu.slurm`):

```bash
sbatch cluster/iridis/bus_check.slurm
```

One check on its own, after the page has been built (it caches the calibrated model):

```bash
.venv-demo/bin/python demo/bus_check.py --date 2026-11-16 --n 16 --uni-term 1
```
