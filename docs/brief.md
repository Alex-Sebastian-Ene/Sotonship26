# Project brief: cruise-day traffic forecast for Southampton

SotonShip 2026, Southampton City track. Team Sotonship26: Keanu Czirjak, Alex-Sebastian Ene and
Edward Denton.

## In one sentence

We help Southampton City Council's traffic officers decide where to put marshals, sign messages and roadworks holds on cruise days around the Southampton docks, using a probabilistic traffic forecast and a learned plan built on public data.

## The problem

- **Scale.** Southampton handled 2.69 million cruise passengers in 2024, 88% of the UK total (DfT
  sea passenger statistics). ABP reported over 3 million in both 2024 and 2025.
- **Where it bites.** On a turnaround day thousands of cars, taxis and coaches converge on a handful of
  dock gates through a few roads: Dock Gate 4 and Platform Road, Dock Gate 10 and West Quay Road,
  the M271.
- **The council has said so itself.** In 2011 its transport manager told councillors that cruise
  growth "causes significant congestion, especially at weekends, by Dock Gate 4", and that it is
  worse when two or more large ships coincide with a football match. Passenger numbers have since
  passed the 2030 figure the council's own Dock Gate 4 road model was built for (about 1.9 million).
- **Today's tools react.** On 8 Nov 2010 four liners caused a back-up onto the public road "that
  we were unable to clear through our traffic control computer". Once the queue has formed it is
  too late; the useful decisions (hold roadworks, book marshals, set signs) are made days ahead.

Sources for every figure: [notes/local-evidence.md](../notes/local-evidence.md).

## The user and the decisions

- **User.** The council's traffic management officers.
- **Decisions supported.**
  - Approve, condition or move a roadworks permit on a dock road on a heavy day. The council can
    set the days works may run when disruption is likely (New Roads and Street Works Act 1991,
    s.56).
  - Book marshals at a dock gate (with the port).
  - Set sign messages on the approaches.
  - Spot clashes: ships, Saints home matches and school holidays on the same roads.
- **Not in scope.**
  - Changing signals or signs automatically.
  - Traffic inside the port.
  - Live incident detection.

## What we built

A forecast page covering the next six weeks of published ship calls:

- **Calendar.** Each day coloured by how much the ships add to congestion, with ships, roadworks and
  home matches marked.
- **Day view.**
  - The headline numbers: hours of congested road the ships add, with a likely range, and the
    worst moment.
  - The chance each main road is over 85% full in every 15 minutes.
  - A map of the real road network with the vehicles of one simulated day moving on it,
    including real bus routes.
- **What to do.** Suggested actions, each with a time window and its owner:
  - marshals at a named gate;
  - a sign message with suggested text;
  - moving a roadworks permit.

  A learned policy's plan sits beside them. Every action needs an officer's approval.
- **Trust panel.** Where each number comes from, when it was collected, whether it is published
  or modelled, and how the model has done on past days.
- **Failure handling.** Dates beyond the published schedule get a refusal, not a guess. Ships
  with no passenger figure are flagged and given a wider range.

## How it works

1. **Inputs, all public and dated.**
   - The ABP Southampton VTS cruise schedule.
   - Ship capacities from the cruise lines.
   - Saints fixtures, school term dates and bank holidays.
   - Street Manager roadworks permits.
   - Port freight calls.
   - Census 2021 commuting and DfT traffic counts.
2. **Road network.** OpenStreetMap roads round the docks, with lanes, speed limits, one-way
   streets and dock gates.
3. **Traffic model.** Every 15 minutes, everyday trips plus cruise cars, taxis, coaches and port
   lorries are routed over up to three real routes each. Traffic that cannot pass a full road
   queues into the next 15 minutes.
4. **Many simulated days.** Each date is simulated many times with varied weather, incidents,
   everyday traffic and passenger behaviour, each once with and once without the ships. That gives
   the odds of congestion and the ships' own effect with a range.
5. **Fitted to observed traffic.**
   - Council counts round Portswood, DfT counts at the edge of the area and DfT lorry counts.
   - The cruise effect learned from 2.5 years of National Highways counts on the M271, matched to
     archived ship schedules.
6. **Decision layer.** A reinforcement-learning policy trained on the simulator chooses marshals,
   signs, check-in timing and disembarkation pacing every 15 minutes; the page shows its plan as
   suggestions.

The design choices behind each step, and why: [decisions.md](decisions.md).

## The AI, and how we know it helps

- **Cruise effect on the M271.**
  - 179 held-out days, Jan to Jun 2026.
  - Error of 877 vehicles a day, against 1,233 for the brief's baseline ("last comparable cruise
    day") and 1,353 for assuming no cruise effect.
  - 87% of held-out days fell inside the 80% band.
  - Most of the gain comes from the calendar; the ship schedule adds 2% per 15 minutes.
  - [backtest.md](backtest.md)
- **Everyday traffic.**
  - At M3 J14, ridge regression on calendar and school-holiday features beats a careful planner's
    five-week year-ago median by 6.6% (90% interval 0.5–12%, 355 held-out days).
  - Refits use only counts National Highways had published by then, about 105 days late.
  - On the M271 it does not beat the year-ago rule, and we say so.
  - [notes/flow-forecast.md](../notes/flow-forecast.md)
- **Decision policy.** On 7 held-out cruise dates (140 simulated days), PPO avoids 3.1 congested
  road-hours a day (95% interval 2.2–3.9; better on all 7 dates), with total delay unchanged, for
  about £2,500 a day of marshal and sign time, about £830 per road-hour avoided. Caveats:
  - In money alone it is a cost, not a saving. The ship-timing advisor saves about £7,100 a day and
    avoids 1.2 road-hours.
  - The effect of marshals and signs, and the cost weights, are assumed. All simulated.

  [ppo-results-aa8eae9.md](ppo-results-aa8eae9.md), [ppo-robust-aa8eae9.md](ppo-robust-aa8eae9.md)

## Limits

- **No public counts next to the docks.** Dock-gate roads are modelled; the nearest sensor is 4 to
  7 km away on the M271.
- **The schedule is provisional.** Most calls have clock times only about six days ahead; earlier
  calls use the typical times in the same feed.
- **Assumed effects.**
  - Marshals: 25% more gate capacity.
  - Signs: drivers see the signed roads as 30% slower.
  - Cost weights: set by us. The council should set them.
- **The macro model simplifies junctions.** A microsimulation cross-check found slow traffic at
  junctions the macro model misses ([sumo-check.md](sumo-check.md)).
- **Past calls are plans, not berthings.** They come from four archive captures, and days no
  capture covers are left out.

## Business case

- **Buyer.** Southampton City Council, under its network management duty (Traffic Management Act
  2004, s.16). A second buyer is the bus operators whose routes cross the dock roads.
- **Cost to run.** One rebuild uses about 18 core-hours: 17 minutes on 64 cores. The page is a
  static file. Inputs are public, so there are no data fees.
- **Price anchor.** Devon County Council paid £29,000 a year for a traffic-data service (Find a
  Tender, Nov 2025). The capital alternative, extending the M271 into the port, was costed at
  £40 million and called "prohibitive" (council inquiry, 2011).
- **Scale-out.** Southampton handles 88% of UK turnaround passengers, so a cruise-only product
  has one large UK customer. The engine generalises to other scheduled events that load roads
  (stadiums, ferry peaks, port freight at Dover and Portsmouth) and to European turnaround ports.

## Responsibility

- **Human control.** Every action is a suggestion with an owner; nothing is applied automatically.
- **Provenance.** Each number shows its source and collection time; modelled and published figures
  are tagged; synthetic inputs are labelled.
- **Data rights.** ABP's schedule data is used for personal reference with acknowledgement and is
  never redistributed. Only aggregates are published.
- **No personal data.** Bus readings are vehicle positions from a public feed, kept only as
  aggregates.

## Where to look

- [README](../README.md): setup, how to build the page, data sources and AI provenance.
- [decisions.md](decisions.md): design decisions and their evidence.
- [design.md](design.md): the original Friday-night plan.
- [notes/](../notes/): the evaluation write-ups and local evidence.
