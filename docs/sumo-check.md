# SUMO check: the macro model's congestion against a microsimulation

The cruise-day forecast (`demo/traffic_model.py`) is a macroscopic model: every 15 minutes it
splits each origin-destination flow over up to three routes, prices each road with a BPR curve
on volume over an assumed capacity, and holds traffic that cannot pass a route's worst link in a
point queue for the next 15 minutes. The bus check in [agents-and-ppo.md](agents-and-ppo.md)
found its queues 2 to 5 times too long on Portswood Road. This document runs the same sampled
days through **Eclipse SUMO**, a microscopic simulator: individual vehicles with car-following,
lane changes, junction priorities and traffic signals on the real road geometry, each with its
own wanted speed, and compares the two per corridor and per 15 minutes.

**Status: a cross-check, not a forecast.** SUMO has had no calibration of its own here (no
signal plans, no junction tuning, no fit to counts). Where the two models disagree, neither is
known to be right; the observed data that exist (WebTRIS on the M271, the council's Portswood bus
times) are shown next to both. Nothing in this document feeds the forecast page.

<!-- RESULTS -->

## How it is built

### Network (`demo/sumo_net.py`)

- **OpenStreetMap roads** for the forecast's box (synthetic_demo.BBOX, -1.53, 50.855 to -1.29,
  50.975), downloaded with the Overpass API on 17 Oct 2026 (OSM data as of 11:57 UTC; © OpenStreetMap
  contributors, ODbL): the same road classes the macro model routes on (motorway to unclassified
  and their slip roads), plus traffic-signal nodes and turn restrictions. No residential streets,
  as in the macro model, so neither model has rat runs.
- `netconvert` (SUMO 1.28.0) with left-hand traffic, OSM lanes, one-ways and speed limits;
  where OSM has no limit, a UK default per class (70 mph motorway, 50 mph trunk, 40 mph slip
  roads, 30 mph otherwise; assumed). Signals are guessed and joined from OSM's signal nodes and
  run as actuated signals with SUMO's default plans (no real timings). Ramps, roundabouts and
  junction clusters are guessed by netconvert. Only the largest connected part is kept.
- Result: 4,986 edges, 2,646 junctions, 126 signalised junctions, 1,234 lane-km.
- **Variant without roundabout signals** (`sumo_net.py no-ring-signals`). OSM marks several big
  interchanges as signalised roundabouts, M27 junction 3 at Rownhams among them. netconvert gives
  each entry its own signal running SUMO's default plan, not linked to the others, and in the first
  runs the ring at Rownhams jammed at 07:00 on a Saturday, with traffic at 3-17% of free speed on
  both M271 carriageways while the macro model put the M271 at V/C 0.46. Real signals on a
  roundabout are linked so the ring keeps moving. The variant drops the signals at the 28 junctions
  run by 24 roundabout-only signal controllers (the roundabouts then give way to circulating traffic). Both are
  run; neither is the real junction control.

### Demand (`demo/sumo_demand.py`)

One sampled day of the forecast, drawn exactly as a forecast sample (`daysim.sample_day`, seed
7, the same day `agents.py` shows), so both models carry the same traffic:

- every kind of everyday trip (`daysim.background_by_purpose`) and match fans, per 15 minutes and
  origin-destination pair, rounded to whole vehicles at random so the expected totals are kept.
  Port freight is in car-equivalents in the macro model; here it becomes lorries (divided by
  2.5) that are 16.5 m long;
- every cruise vehicle the day draws (`daysim.cruise_vehicles`) at its own minute; coaches are
  13 m coaches. The cruise assumptions are the forecast's fitted ones (road ×1.15, 60% from the
  county), read from the forecast page;
- the local traffic the macro model adds on the four counted roads (Portswood Road, Highfield
  Lane, St Denys Road, Bevois Hill) as trips along each road;
- the day's buses from the BODS timetable (`demo/buses.py`: Bluestar and First's X4/X5; Unilink
  is not in BODS), stopping 20 s at each stop and never leaving before the timetabled time.

Trip ends are spread over the network instead of loaded at one node: a zone's trips start and
end on random local roads nearer to that zone than to any other (weighted by length), a county
gateway's on its main road near the edge of the area (inbound to start, outbound to end), dock
gates, the station and the stadium on roads within 250 m. Each trip leaves at a random second of
its 15 minutes. Wanted speeds are drawn per vehicle: cars `normc(0.92, 0.06, 0.75, 1.0)` times the
limit, lorries and coaches 0.95 (capped at 56 mph), buses 0.92 (capped at 45 mph).

### Routing and simulation

One-shot dynamic assignment: every vehicle is routed when it enters on the travel times then
measured (smoothed over 3 minutes) and re-routed every 5 minutes; each routing call disturbs edge
costs by a random factor up to 1.2 so drivers do not all take the single quickest road. This is
not an equilibrium like the macro model's per-bin averaging, but it reacts to queues. A vehicle
stuck for 5 minutes is moved ahead ("teleported", SUMO's way of breaking gridlock; counted
below); vehicles blocking a junction are ignored after 60 s; a vehicle that cannot enter the
network within an hour is dropped (counted). The microscopic run steps every second. The
mesoscopic run (`--mesosim` with junction control) uses SUMO's queue model on 100 m segments
instead of car-following, as a faster second opinion.

The macro reference is `traffic_model.run_day` on the same sampled day, with dry roads and no
incident so both models see the same road capacity (the forecast's own sample may draw rain or a
breakdown; the trips are the sampled ones either way).

### Comparing (`demo/sumo_compare.py`)

Corridors are the forecast page's (synthetic_demo.CORRIDORS plus the dock-gate approaches). Each
macro corridor link is matched to the SUMO edges lying along it in the same direction (60% of
the SUMO edge within 20 m and 40° of the macro link). Per corridor, direction and 15 minutes:

| measure | macro model | SUMO |
| --- | --- | --- |
| flow | median link volume, capped at capacity (car-equivalents per hour); the uncapped volume is the demand | median link throughput (vehicles leaving the link, per hour) |
| delay | minutes over free flow: BPR running time on the corridor's links plus the page's queue wait, 15 min × (V/C − 1) at the worst link | measured travel time over each link minus its length at 92% of the limit, summed |
| queue | the most vehicles a corridor link could not pass in the 15 minutes | mean number of vehicles standing still on the corridor (waiting time / 900 s) |
| congested | V/C > 0.85 ("busy") or > 1 ("jammed") | speed below 70% or 50% of free flow |

Network totals use the macro model's own accounting: slower running on every link plus 15
minutes for every vehicle its point queues carry into the next bin; SUMO's are time lost on the
roads plus time waiting to enter.

### Running it (Iridis)

See the header of `cluster/iridis/sumo.slurm`: SUMO runs from the official container (the pip
`eclipse-sumo` wheels crash at start-up on Iridis' RHEL 8 nodes), one array task per day,
microscopic and mesoscopic side by side; `MODES` and `SIM_THREADS` pick the runs and SUMO's
parallel stepping. Outputs go to `runs/sumo/<date>/` (gitignored): trips, SUMO outputs,
`compare.json` and `compare.md`.
