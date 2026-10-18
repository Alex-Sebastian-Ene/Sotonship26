# Why the simulator over-predicted the M271, the Redbridge Causeway and the A335 (SOT-27)

Written Sat 17 Oct 2026 with Claude Code in Alex-Sebastian's session (SOT-27).
Counts: DfT road traffic statistics, annual average daily flow 2025 (published June 2026, OGL v3).
Model numbers are the city simulator (`demo/traffic_model.py`), one deterministic weekday,
05:00-20:00, in car-equivalents (a lorry is 2.5), on `seb/SOT-24-port-freight` (fcf09fd) unless
stated. Everything here comes from the model, not from observations, except the DfT counts.

## Before: what loaded the M271 between the A35 and junction 1 (DfT 26062)

The DfT fit (Iridis job 1888960) had the M271 at +90%, the A35 Redbridge Causeway (36375) at +66%
and the A335 Thomas Lewis Way (18312) at +62%, while the A33 Redbridge Road (90217) was at -23%
and Millbrook Road West (56347) at -21%.

| Link | Model load | Demand routed over it | Trip types | From / to (largest) |
|---|---:|---:|---|---|
| M271 northbound (3753) | 65,321 | 37,098 | other county trips home 39%, port freight 13%, within the area 13%, other county trips in 11%, through 7% | from Totton 16%, Dock Gate 20 11%, Millbrook 10%, A326 south 8%; to M27 west 30%, M3 north 21%, M27 east 12% |
| M271 southbound (1606) | 41,384 | 32,113 | other county trips in 39%, within the area 16%, port freight 15%, other trips home 9% | from M3 north 24%, M27 west 23%, M27 east 13%; to Millbrook 14%, Dock Gate 20 12%, Totton 12%, A326 south 11% |
| Causeway eastbound (6052) | 85,935 | 46,675 | within the area 31%, other trips home 21%, other trips in 21%, through 9% | from Totton 24%, A326 south 15%, Langdown 14%, A3090 west 9% |
| Causeway westbound (960) | 40,094 | 30,970 | within the area 28%, other trips in 23%, other trips home 22% | to A326 south 21%, Totton 18%, Eling 16%, A35 west 10% |
| A335 northbound (3102) | 27,519 | 20,030 | other trips home 46%, within the area 31% | to M3 north 21%, M27 east 19%, M27 west 11% |
| A335 southbound (2699) | 23,732 | 17,544 | other trips in 53%, within the area 20% | from M27 east 29%, M3 north 21% |

"Demand routed over it" is each trip type's demand times its routes' share of that link, counted
once when it sets off. "Model load" is what the DfT fit compared with the count.

## Causes

**1. Queues were counted again every 15 minutes.** Traffic that cannot get past the bottleneck of
its route waits and joins the next 15 minutes (`run_day`). It was put back on every link of its
route each time, and the DfT and council fits compared those link loads with the counts. Upstream
of a jammed junction a car could be counted many times: the M271 northbound load was 65,321 against
37,098 routed. At the old scale, counting each vehicle once puts the M271 at +7% and the Causeway at
+12%, but the M27 and M3 fall to -26% to -39%: the old fit had matched the motorways only because
of the same double counting. The worst jams, 12 to 14 hours a day over capacity, were the one-lane
A35 slip from the Causeway to Redbridge roundabout (on 56% of the held-back Causeway traffic and
30% of the M27 junction 3-4 traffic), the M27 junction 3 slip, the A33 slips at Redbridge,
Windhover (M27 junction 8) and Leigh Road at M3 junction 13.

**2. The Totton Western Bypass (A326) was missing northbound.** It runs along the west edge of the
area into M27 junction 2 at Ower, and cutting OSM to the area removed the northbound carriageway
(the southbound one survived). Every trip from Totton, Calmore, the Waterside and the A3090 to the
M27 or M3 was routed over the Causeway, Redbridge roundabout and the M271 instead: Totton to the
M27 west gateway took 7.2 minutes free-flow via Redbridge against 4.4 minutes the other way. DfT
counts 27,898 vehicles a day on that bypass (count point 99867). This made the Causeway and the
M271 northbound the busiest roads on the west side and caused the one-lane slip jam above.

**3. The M27 eastbound was missing through junction 3.** OSM has it (ways 151025941 to 25789767,
3 lanes), but the network has no eastbound carriageway from the west edge through Rownhams;
`repair_motorways` rebuilt it only as far as the west side of the junction. All eastbound M27
traffic, including through traffic to the M3 and Portsmouth, left by the slip, went round the
Rownhams roundabout and rejoined by a two-lane slip that was over capacity 13 to 14 hours a day.
It was the main reason the M27 junction 3-4 count came out low once queues were counted once.

**4. Two smaller ones.** The M3 southbound south of junction 13 is two 2-lane carriageways in OSM
(ways 146454517 and 146454543); the network has one. And at the A33 Redbridge Road count point
(90217) the model counted the Millbrook Flyover as the inbound side, though the inbound road splits
at the count point into the flyover and the slip to Millbrook roundabout: it counted 20,000 of
47,000 inbound vehicles on a weekday.

With the motorways short and the A33 Redbridge Road half counted, the DfT fit had to scale all
county traffic up (x1.25 to x1.6 once queues were counted once), so every gateway carried 1.25 to
1.6 times its own DfT count, and the extra flooded the Causeway and the city roads.

Things checked and ruled out: lowering the port land jobs weight to 0.1 only moved the M271 to
+74% (before these fixes); the OSM lane counts at Redbridge are mostly tagged (one-lane slips are
real); port freight was added after the over-prediction already existed (+58% on main).

## Fixes

1. `run_day` can return `count`: each vehicle once, on the links before its route's bottleneck when
   it sets off and on the bottleneck and after it when it gets through. The DfT fit
   (`modelled_aadf`), the lorry fit (`modelled_lorries`) and the council-count fit and local
   traffic (`flows`) use it. `x` (demand over capacity, which the page's risk numbers use) is
   unchanged.
2. `repair_motorways` adds the M27 eastbound through junction 3, the A326 northbound into junction
   2 (with the A36's slip onto it) and the second M3 southbound carriageway's lanes
   (`MISSING_LINKS`, `LANE_FIXES`).
3. `count_point_edges` takes the other direction on the same named road where there is one within
   60 m (only 90217 changes).
4. `build_ctx` fits the county scale and the city scale in turn, twice, before the lorry fit: both
   load the count points.
5. Refitted with those: `THROUGH_SHARE` 0.3 to 0.6 and `OTHER_T_S` 900 to 1800 s (scan in the
   comment in `traffic_model.py`). The county scale now comes out at x1.00, so every gateway carries
   its own DfT count.
6. The lorry fit (`calibrate_freight`) keeps every HGV count point at or under 95% port lorries
   (`FREIGHT_HGV_LIMIT`). Every lorry to or from Dock Gate 20 (70% of them) runs M271, Redbridge,
   A33 Redbridge Road, Millbrook roundabout, so the A33 Redbridge Road (90217, 4,700 lorries
   counted) must carry at least the M271's port lorries; 85% of the M271's 5,882 (an estimated
   count) is 5,000, more than that. With the inbound side counted properly (fix 3) the old fit put
   121% of 90217's lorries on it. The fit now takes the scale nearest the M271 target that keeps
   every point under the limit, and marks the row where the limit binds (`binding`); the M271 then
   carries less than 85% and says so.

### Result (full rebuild on Iridis, job 1890434, against job 1888960 on fcf09fd)

| DfT count point (AADF 2025) | Observed | Before | After |
|---|---:|---:|---:|
| 26062 M271, A35 to junction 1 | 53,320 | +90% | +10% |
| 90217 A33 Redbridge Road | 69,132 | -23% | -10% |
| 36375 A35 Redbridge Causeway | 61,994 | +66% | +34% |
| 56347 A33 Millbrook Road West | 49,004 | -21% | -38% |
| 57434 A33 The Avenue | 27,474 | -23% | -26% |
| 18312 A335 Thomas Lewis Way | 31,027 | +62% | +31% |
| 17793 M27 junctions 3-4 | 136,437 | -5% | -12% |
| 48091 M27 junctions 4-5 | 112,272 | +4% | +11% |
| 38083 M27 junctions 7-8 | 114,831 | +3% | +4% |
| 16321 M3 junctions 13-14 | 140,751 | -12% | -7% |
| Mean absolute error, 10 fitted points | | 30.9% | 18.3% |
| Same without the M271 | | 24.3% | 19.2% |
| Checks: Itchen Bridge / Northam Bridge | 18,300 / 24,312 | +69% / -33% | +51% / -35% |

- Scales: county x0.80 to x1.00, trips within the area x0.95 to x1.42, port lorries x1.20 to
  x1.30 (3,380 each way on a weekday). The lorry limit binds at the A33 Redbridge Road (91% of its
  4,700 lorries); the M271 carries 3,728 port lorries, 63% of its 5,882, short of the 85% aimed
  for. Every other HGV check point is at 60% or less.
- Portswood count sites, weekday sums (fitted): AM 6,404 against 5,534 counted (+16%), PM 5,796
  against 6,549 (-11%). Before: +17% and -4%.
- M271 cruise fit: RMSE 13.7 vehicles per 15 minutes (was 14.1). It now picks the default cruise
  assumptions (car and taxi x1.0, 80% from the county, no shift) instead of x1.15 and 60%.
- The forecast shows more congestion: corridor-hours at risk per day average 106.4 over the 44
  days (was 76.6), maximum 154.0 (was 135.1). After main's queue calibration and its refit for
  this branch (COUNT_HEADROOM 1.3, no capacity anchor where the zones already fill a road; see
  "Refit after SOT-27" in docs/queues.md) it is 91.8 with ships (Iridis job 1891089), against
  71.5 on main. The Portswood bus check is then 1.20 minutes off the council's July figures
  without Bluestar 20 northbound (main 1.72 with it), and 2.88 with it. The model now carries traffic volumes that match the
  counts when each vehicle is counted once, while the risk measure (demand over capacity) still
  includes queued traffic on the links before its bottleneck (see below).

## Not fixed

- **The Causeway is still about +34%.** Its demand is above its capacity much of the weekday, so
  its count follows capacity more than demand. The rest of the over-supply is trips between
  Totton and the Waterside and the M3 and M27 east, and zone access points that jam all day
  (Hillyfields on Redbridge Lane, 800 an hour, peaks at 5 to 7 times capacity).
- **Queued traffic still takes road space twice in the assignment.** `run_day` puts waiting traffic
  back on every link of its route each 15 minutes, so it uses the capacity of links it has already
  passed. That is why the M271 cruise fit still compares link loads: counted once, extra cruise
  cars mostly displace other traffic at Redbridge, and the fit's error is 19.6 vehicles per
  15 minutes instead of 13.7. The fix is to keep each route's queue at its bottleneck and load it
  only on the links from there on. Done in SOT-30 (`docs/bottleneck-queues.md`).
- A33 Millbrook Road West (-38%) and The Avenue (-25%) are under; the Itchen Bridge (no toll in
  the model) is over.
