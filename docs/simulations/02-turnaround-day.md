# 02 · Turnaround Day

**Page:** `frontend/day.html` · **Code:** `frontend/js/sims/day.js`, `frontend/js/core/staffing.js`

## Question it answers

"How many staff do I need on each hour of Saturday?" This is the business page. It turns the
simulation into the number a manager acts on.

## What you see

- A synthetic four-ship Saturday: three turnaround ships (Ocean, Horizon, Mayflower) and one port
  call at QEII, 05:00 to 20:00. All four kinds of flow are on: disembarking walkers, boarding
  passengers arriving by train and ferry, port-call passengers doing a day ashore and returning,
  and crew on shore leave.
- Under the map, a strip with one bar per ship alongside and a "now" line, sharing the x-axis with
  the chart of people walking and in venues.
- **Staffing plan** for the selected venue: one column per hour for the staff the forecast says it
  needs, a dashed line for the flat roster, and the staff-hours and money saved so far.
- **All venues today**: peak occupancy against capacity, peak staff, estimated spend and the saving
  from the forecast roster. Download it as CSV.

## Design decisions

| Decision | Why |
| --- | --- |
| Staff needed = ceil(90th-percentile occupancy in the hour ÷ customers per staff), minimum 2 | Staffing to the mean leaves the busiest quarter-hour short. Staffing to the absolute peak overstaffs for a single spike. The 90th percentile is a common middle ground; it is one constant in `staffing.js`. |
| Baseline is a flat roster: the forecast peak, all day | That is what businesses describe doing on cruise days ("we just staff up"). It is also generous to the baseline, because it assumes they guessed the peak correctly. |
| Savings in staff-hours and £ at the National Living Wage (£12.71/h, 21+, from April 2026) | A café owner thinks in shifts and pounds, not occupancy curves. The wage is one constant for each business to change. |
| Opens at 08:15 with ships already disembarking; "Jump to" buttons | A full day at 360× takes about 2.5 minutes. Jumps re-run the seeded day up to the chosen time, so they are deterministic and fast (a full day takes under a second). |
| "New sampled day" changes the seed | Shows that the forecast is a distribution. The Monte Carlo backend (`forecast/montecarlo.py`) turns many such days into probabilities; this page shows one sample at a time. |
| Ship bars share the chart's x-axis exactly | You can read "the dip at 11:00 is the gap between disembarking and boarding" straight off the screen. |
| Rain toggle | Weather is the second input in the track brief's example. Here it moves utility away from parks and towards shops and SeaCity Museum. |
| CSV columns are venue, hour, p90, peak, staff | The format a rota spreadsheet can take, and the shape of the product's actual deliverable. |

## Controls

Speed, weather, walk share, jump to a time, new sampled day, venue picker (or click a venue on the
map or in the table), CSV download.

## Backend hooks

- Replace `SAMPLE_DAY` with the parsed VTS schedule (`data/cruise.py` has the same fields: ship,
  terminal, arrival, departure, passengers).
- Replace the single sampled day with the Monte Carlo output to draw bands (P10–P90) instead of a
  single line, and size staff to P90 across days as well as within the hour.

## Next

- A local-trade baseline per venue, so the forecast shows cruise demand on top of normal Saturday
  trade rather than as reduced capacity.
- Per-business split of each cluster.
