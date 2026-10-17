# Sotonship26

We help Southampton City Council's traffic management team decide which cruise days and hours need
traffic marshals, sign messages and a hold on roadworks around the docks. The forecast is
probabilistic: for each road corridor and 15-minute slot it gives the chance of congestion and the
extra traffic the ships add, with a 10/50/90% range. The inputs are the VTS cruise schedule, Saints
home fixtures, school term dates, roadworks permits and port freight, run over the real road
network and checked against observed traffic. [docs/design.md](docs/design.md) has the full plan.

The product is vehicle traffic, not people on foot (team decision, Sat 17 Oct 2026). The footways
round the terminals are wide enough that walking passengers don't change any decision the council
makes. The pedestrian and waterway code from the first design is still in the package but is not
part of the product.

## How it fits together

```mermaid
flowchart TD
    subgraph inputs["Inputs, real, dated, cited"]
        vts["VTS cruise schedule<br/>ships · berths · passengers"]
        cal["Saints fixtures · school terms<br/>bank holidays"]
        permits["Street Manager<br/>roadworks permits"]
        freight["Port freight calls<br/>container + RoRo"]
        census["Census + DfT gateway<br/>commuter / through traffic"]
    end

    subgraph model["Traffic model on the real road network"]
        trips["Vehicle trips per 15-min bin<br/>cars · taxis · coaches · lorries · buses"]
        net["OSM directed road graph<br/>lanes · dock gates"]
        route["Route choice + queues<br/>carried between bins"]
        mc["Monte Carlo over sampled days<br/>paired with / without ships"]
    end

    subgraph calib["Fitted + checked against observed traffic"]
        webtris["WebTRIS 15-min<br/>M271 · M3 J14"]
        dft["DfT AADF + hourly counts"]
        imagery["Aerial car-park occupancy<br/>+ camera vehicle counts"]
    end

    out(["P(congestion) per corridor per 15 min<br/>+ cruise uplift, 10 / 50 / 90% range"])

    subgraph product["demo/page.html, what the council sees"]
        calendar["Calendar<br/>days coloured by risk"]
        dayview["Day view<br/>corridor × 15-min heatmap + map"]
        whatif["What-if<br/>close a road, rerun before/after"]
    end

    vts --> trips
    cal --> trips
    permits --> trips
    freight --> trips
    census --> trips
    trips --> net --> route --> mc --> out
    calib -. "calibrate / backtest" .-> model
    out --> calendar
    out --> dayview
    out --> whatif
```

| Module | What it does |
| --- | --- |
| `data/vts.py` | Real cruise schedule from the VTS feed, with lower-berth capacity per ship |
| `data/vts_freight.py` | Container and RoRo calls per day, for port lorry demand |
| `data/dft.py` | DfT road traffic counts (yearly averages and hourly counts) near the docks |
| `data/observed.py` | WebTRIS 15-minute observed flows on the M271 and M3 |
| `data/roads.py`, `corridors.py` | Directed road graph, corridors, terminal-to-gate table, candidate paths |
| `flow_forecast.py` | Ridge forecast of everyday traffic, scored against planner baselines |
| `uplift.py`, `uplift_model.py`, `backtest.py` | Cruise-day uplift target, baselines and backtest |
| `imagery/`, `vision/` | Car-park occupancy from aerial tiles; vehicle counts from camera stills |
| `demo/` | The forecast page: traffic model on the real network, real inputs, `page.html` |
| `data/streets.py`, `data/waterway.py`, `data/tides.py`, `demand/`, `rl/` | First design (pedestrians and waterway), parked |

Settings, with the guesses that still need calibrating marked as such, live in
[configs/default.yaml](configs/default.yaml).

## Setup

Uses [uv](https://docs.astral.sh/uv/) and Python 3.12. PyTorch comes in one of four builds, chosen
per machine with an extra:

| Extra | For |
| --- | --- |
| `cu130` | NVIDIA Turing or newer (RTX 20xx+, A100, H100, Blackwell) with a CUDA 13 driver |
| `cu126` | Older NVIDIA GPUs (Pascal/Volta) or drivers older than CUDA 13 |
| `rocm` | AMD GPUs with ROCm 7.x (Linux only) |
| `cpu` | No GPU |

The setup scripts detect the right one, install uv if needed, sync and run a GPU check:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_env.ps1   # Windows
```

```bash
bash scripts/setup_env.sh          # Linux / AMD box (detects nvidia-smi or ROCm)
bash scripts/setup_env.sh cu126    # or name the backend explicitly
```

Plain `uv run` syncs back to no extra and swaps out the GPU build, so after setup either pass the
extra (`uv run --extra cu130 ...`) or activate `.venv`. The chosen backend is saved in
`.torch-backend`.

`python -m sotonship26` reports the torch build and runs a matmul on the GPU.

### Iridis

1. Copy [cluster/ssh_config.example](cluster/ssh_config.example) into `~/.ssh/config` with your
   username, then `ssh iridis`.
2. Clone the repo on Iridis and, on the login node, run `bash scripts/setup_env.sh cu126` (login nodes have
   no GPU, so name the backend; use `cu130` if `nvidia-smi` on a GPU node shows CUDA 13+, or `rocm`
   for AMD GPU nodes). The script puts uv's cache under `/scratch/$USER` when it exists.
3. `sbatch cluster/iridis/gpu_check.slurm` to confirm torch sees the GPU on a compute node.
4. `sbatch cluster/iridis/train.slurm --scenario streets --timesteps 500000`.

Check partition names with `sinfo -s` and edit the `#SBATCH --partition` lines to match.

### AMD (ROCm)

`bash scripts/setup_env.sh rocm` installs the ROCm 7.2 PyTorch build. torch still exposes the GPU as
`cuda` under ROCm, so the same code runs. Consumer Radeon cards that ROCm doesn't officially list may
need `HSA_OVERRIDE_GFX_VERSION` set to the nearest supported target.

## Running

```bash
uv run --extra cu130 sotonship-eval --scenario streets     # Monte Carlo forecast, writes runs/*.csv
uv run --extra cu130 sotonship-eval --scenario water
uv run --extra cu130 sotonship-train --scenario streets    # PPO, TensorBoard logs in runs/tensorboard
uv run --extra cu130 pytest
uv run --extra cu130 ruff check .
```

## Data sources

The `streets` and `water` scenarios that run today are **synthetic test data**, and the CLI says so.
Fill in the date collected and the licence for every source before submission.

| Source | Used for | Collected | Licence |
| --- | --- | --- | --- |
| [ABP Southampton VTS cruise ship schedule](https://www.southamptonvts.co.uk/live_information/shipping_movements_and_cruise_ship_schedule/cruise_ship_schedule/) (the XML file behind the public page, no API) | Ship, berth → terminal, arrival and departure for 17 Oct to 29 Nov 2026, written by `demo/collect_schedule.py` to `data/raw/cruise_schedule.csv` (gitignored, never committed). Each row records when it was collected. The schedule is provisional. Only the next few days have clock times; for TBA/AM/PM entries the script uses the median exact times in the same feed (06:15 and 17:00). The page shows the XML times unchanged, so they are read as UK local time. | 17 Oct 2026, 00:20 BST (feed last modified 16 Oct, 23:16 GMT) | © ABP, all rights reserved. The [terms of use](https://www.southamptonvts.co.uk/terms_of_use/) allow extracts for personal reference only, so the data is read locally and not redistributed. The page always credits ABP. |
| ABP Southampton VTS cruise ship schedule, [Internet Archive](https://web.archive.org/) captures of the same page dated 13 Jan 2024, 25 Sep 2024, 4 Jul 2025 and 8 Dec 2025 | Past cruise calls for the M271 backtest (`demo/webtris_backtest.py`, `docs/backtest.md`): 792 calls on 625 of 912 days, Jan 2024 to Jun 2026. Raw captures and the rebuilt call list stay in `data/raw/` (gitignored, never committed); only aggregate results are published. | Retrieved 16 Oct 2026 | © ABP, all rights reserved. Used for personal reference with ABP acknowledged, as the [terms of use](https://www.southamptonvts.co.uk/terms_of_use/) allow; not redistributed. Team decision 17 Oct 2026 (SOT-21). |
| Cruise lines' published ship facts (P&O Cruises, Cunard, Celebrity, MSC, AIDA, Princess, Fred. Olsen, TUI Cruises, Oceania, NCL) | Passenger capacity per ship, keyed on IMO number, aiming at two guests per cabin. Each figure's basis and URL is in `CAPACITY` in `demo/collect_schedule.py` and in the CSV's `capacity_source` column. AIDA and MSC Preziosa publish only cabins and a maximum, so their figure is 2 × cabins. Cunard, TUI and some P&O pages give an unqualified "guests" number, used as published. Regatta's figure (670) comes from Oceania's withdrawn page: the ship has been on charter since Sep 2026. | 16-17 Oct 2026 | Facts cited to the operator's page; nothing copied beyond the figure |
| Southampton FC: [2026/27 fixtures](https://www.southamptonfc.com/en/news/article/2026-27-fixtures-saints-start-away-to-watford) (25 Jun 2026) and [Sky Sports selections](https://www.southamptonfc.com/en/news/article/six-saints-fixtures-selected-for-sky-sports-coverage) (30 Jul 2026) | `MATCHES` in `demo/synthetic_demo.py`: home league games on 17 Oct (15:00), 31 Oct (15:00), 21 Nov (12:30) and Fri 27 Nov (20:00) | 16 Oct 2026 | Dates and kick-offs are facts, cited to the club. TV picks can still move them. |
| Southampton City Council [school year calendar 2026-27](https://www.southampton.gov.uk/schools-learning/school-information/school-term-dates/school-year-calendar-2026-27/) | `HALF_TERM` (26 to 30 Oct 2026) and `TERM_ENDS` (18 Dec 2026). The calendar is for maintained and voluntary-controlled schools; academies may differ. | 16 Oct 2026 | No licence stated on the page; dates cited to the council |
| DfT Street Manager open data, [permit archive](https://department-for-transport-streetmanager.github.io/street-manager-docs/archived-notifications/) `permit/2026/08.zip` and `09.zip` (written 1 Sep and 1 Oct 2026) | `PERMITS` in `demo/synthetic_demo.py`: five granted daytime works with signals or a lane closure on the corridors (Platform Road 19-23 Oct and 2-6 Nov, Portswood Road 19-30 Oct and 20-23 Oct, M271 29-30 Oct). Left out: overnight-only lane closures (M271, Millbrook Road West, Mountbatten Way, Redbridge Road, 4-7 Nov), a 07:00-09:00 closure on Northam Bridge (Sun 18 Oct), applications not granted by 30 Sep (Western Esplanade 19-24 Oct and 2-3 Nov, The Avenue 24 Nov, M27 overnight 22-23 Oct) and works that only encroach on the carriageway. Permits granted in October are not archived until 1 Nov, so later short-notice works are missing. | 16 Oct 2026 (events up to 30 Sep 2026) | Open Government Licence v3.0 |
| Southampton VTS cruise schedule: the XML feed behind the [cruise ship schedule page](https://www.southamptonvts.co.uk/live_information/shipping_movements_and_cruise_ship_schedule/cruise_ship_schedule/) | Ship calls, fetched live by `data/vts.py` and cached in `data/raw/vts/`, not committed | At run time; `collected_at` on every row (first pull 16 Oct 2026) | © ABP, all rights reserved; we don't redistribute it |
| Ship lower-berth capacity, 22 ships (Wikipedia, cruise line and cruisemapper pages; URL per row) | `passengers` per call, `src/sotonship26/data/ship_capacity.csv` | 16 Oct 2026 | Facts with the source cited on each row |
| UKHO ADMIRALTY UK Tidal API (Discovery tier, key in `UKHO_API_KEY`) | High/low water predictions | TODO | TODO |
| OpenStreetMap via osmnx | Walking network around the terminals; directed road network and dock gate locations (`data/roads.py`) | Roads: 16 Oct 2026 (OSM base 21:45 UTC) | ODbL |
| Bathymetry + water polygon for Southampton Water | Replace the synthetic lattice | TODO | TODO |
| Footway widths, pedestrian counts on turnaround days | Calibrate capacities | TODO | TODO |
| Red Funnel / Hythe ferry timetables, leisure-craft activity | Waterway demand | TODO | TODO |
| ONS Census 2021 ODWP01EW, location of usual residence and place of work (MSOA), [Nomis bulk download](https://www.nomisweb.co.uk/sources/census_2021_od) | Demo: commuters into and out of the study area, where they live or work, which gateway they use (`demo/external_data.py`, `data/cache/census`, not committed). Census day was 21 Mar 2021, in lockdown | 16 Oct 2026 | Open Government Licence v3.0 |
| ONS Census 2021 method used to travel to work by distance travelled, per local authority ([census API](https://api.beta.ons.gov.uk/v1/population-types/UR/census-observations?area-type=ltla&dimensions=transport_to_workplace_12a,workplace_travel_10a)) | Demo: share of each commuter flow driving a car or van | 16 Oct 2026 | Open Government Licence v3.0 |
| ONS MSOA (Dec 2021) population-weighted centroids V2, Open Geography Portal | Demo: placing each MSOA inside or outside the study area | 16 Oct 2026 | Open Government Licence v3.0; contains OS data © Crown copyright and database right |
| DfT road traffic statistics, AADF per count point ([dft_traffic_counts_aadf.zip](https://roadtraffic.dft.gov.uk/downloads), published Jun 2026, 2025 counts) | Demo: traffic crossing each county gateway (count point on the gateway road), less census commuters and visitors, split 30% through traffic and 70% other trips to the area's zones; scale for everything crossing the edge of the area fitted to 10 count points and checked at 2 more (M271, A33 Redbridge Road, A35 Redbridge Causeway, A33 Millbrook Road and The Avenue, Itchen Bridge, Northam Bridge, A335, M27, M3) (`data/cache/dft`, not committed) | 16 Oct 2026 | Open Government Licence v3.0 |
| National Highways [WebTRIS](https://webtris.nationalhighways.co.uk/api/swagger/ui/index) 15-minute counts, M271 (sites 19974, 19796, 20313, 20605, 7588) and M3 J14 (20025) | Observed traffic for the everyday forecast and its backtest (`data/observed.py`, `flow_forecast.py`), cached in `data/raw/webtris/`, not committed | 16–17 Oct 2026; counts 2024-01-01 to 2026-06-30 (about 3.5 months publication lag) | Open Government Licence v3.0 (contains National Highways information) |
| Southampton City Council [school term dates](https://www.southampton.gov.uk/schools-learning/school-information/school-term-dates/), 2024-25 to 2026-27 live pages, 2023-24 from the [Wayback Machine copy](https://web.archive.org/web/20240303065857/https://www.southampton.gov.uk/schools-learning/school-information/school-term-dates/school-year-calendar-2023-24/) | `SCHOOL_HOLIDAYS` feature in `flow_forecast.py` | 17 Oct 2026 | Facts (dates) with the source cited in the code |
| GOV.UK [bank holidays](https://www.gov.uk/bank-holidays), England and Wales 2024–2026 | `BANK_HOLIDAYS` in `uplift.py` | 16 Oct 2026 | Open Government Licence v3.0 |

**ABP attribution.** Cruise schedule data, current and archived, © Associated British Ports
(Southampton VTS). It is used for personal reference with ABP acknowledged, as ABP's terms allow.
Raw pages and call lists are never committed, and only aggregates are published.

**Limits of the cruise backtest.** Past calls are provisional plans captured on four dates, not
actual berthings. Days no capture covers (Jul 2024, Jan to Aug 2025) are left out rather than
counted as non-cruise days. The traffic is one motorway sensor (M271 northbound), 4 to 7 km from
the terminals. Most of the model's gain over the baselines comes from the calendar: adding ship
data improves it by about 4% a day (not significant) and 2% per 15 minutes.
| DfT road traffic statistics, AADF by direction and hourly raw manual counts (API, Southampton LA 137) | Background traffic and hourly profile on counted roads, fetched by `data/dft.py`, cached in `data/raw/dft/`, not committed | At run time (first pull 16 Oct 2026) | Open Government Licence v3.0 |
| [Bus Open Data Service](https://data.bus-data.dft.gov.uk/timetable/download/) timetables, GTFS for the South West region (Southampton's operators are there) | Demo: Bluestar routes and timetables (and First's X4/X5; Unilink is not in BODS) run on the modelled link speeds (`demo/buses.py`); modelled bus delays per route compared with the council's Portswood bus run times (Table 3-5). Reduced to `data/cache/bods/southampton_buses.json`, not committed; the download time is in `gtfs_south_west.source.json`. Fallback if BODS is unreachable: OpenStreetMap route=bus relations (ODbL), stops only, and the page says so | 17 Oct 2026 | Open Government Licence v3.0 |
| [bustimes.org](https://bustimes.org) live vehicle positions (`/vehicles.json` only; its robots.txt disallows `/api/` and `/trips/`, which we don't use), which republish the BODS live feed | Observed bus lateness on the day: delay against the timetable per line, and per hour near the docks, in the city centre and on Portswood Road (`src/sotonship26/data/bus_lateness.py`, `scripts/bustimes.py`). Raw readings stay in `data/raw/buses/`, not committed; the page shows aggregates with the collection window | From 17 Oct 2026, polled once a minute | BODS data, Open Government Licence v3.0, via bustimes.org |
| OpenStreetMap roads via the [Overpass API](https://overpass-api.de/) (motorway to unclassified and their slip roads, traffic signals, turn restrictions, in the study box) | SUMO check: the microsimulation's road network (`demo/sumo_net.py`, built with Eclipse SUMO's netconvert; `data/cache/sumo`, not committed), compared with the macro model in `docs/sumo-check.md` | 17 Oct 2026 (OSM base 11:57 UTC) | ODbL 1.0 |

## Provenance

- **AI-generated:** the project scaffold (`pyproject.toml` backend extras, `src/`, `tests/`,
  `scripts/`, `cluster/`, `configs/`, this README) was generated with Claude Code on
  Fri 16 Oct 2026. On 16-17 Oct 2026 Claude Code also wrote `demo/collect_schedule.py`, the
  real-input wiring in `demo/synthetic_demo.py` (`make_schedule`, `MATCHES`, `HALF_TERM`,
  `PERMITS`, `SOURCES`) and the source labels in `demo/page.html`. It also looked up and
  transcribed the fixtures, term dates, ship capacities and Street Manager permits listed under
  Data sources.
- **AI-generated (backtest):** `demo/webtris_backtest.py` (data loading, the gradient-boosted
  uplift model, baselines and backtest) and `docs/backtest.md` were written with Claude Code on
  Fri 16 to Sat 17 Oct 2026, following the data choices in `notes/data-spike.md`.
- **AI-generated (page redesign):** the layout, styles and wording of `demo/page.html` (day briefing,
  to-do list, plain-language labels, folded method sections) were rewritten with Claude Code on
  Sat 17 Oct 2026 (SOT-26). The data and the charts it draws are unchanged.
- **AI-generated (ML-fitted cruise assumptions):** the fit of the simulator's cruise assumptions
  to the learned M271 uplift (`cruise_sets`, `m271_probe`, `cruise_fit_tasks` and the fit step in
  `demo/synthetic_demo.py`), the ships-only profiles exported by `demo/webtris_backtest.py`, the
  page panel showing the fit, and `cluster/iridis/forecast.slurm` were written with Claude Code
  on Sat 17 Oct 2026.
- **AI-generated (past-flow check):** `demo/ridge_history.py` (ridge and boosted models with
  past-flow features, refit at publication delays of 1, 7, 28 and 105 days, week-block bootstrap)
  and `docs/ridge-history.md` were written with Claude Code on Sat 17 Oct 2026 (SOT-25).
- **AI-generated:** `demo/external_data.py`, the census commuter gateways (`census_od`), through
  traffic and other county trips from DfT gateway counts (`cordon_od`), the DfT count fit
  (`calibrate_external`) and the motorway repairs (`repair_motorways`) in `demo/traffic_model.py`
  were written with Claude Code on 16-17 Oct 2026.
- **AI-generated (road network):** the directed road network, corridors and candidate paths
  (`src/sotonship26/data/roads.py`, `src/sotonship26/corridors.py`, their tests, the `roads:`
  block in `configs/default.yaml`) were written with Claude Code on Sat 17 Oct 2026 (SOT-9).
- **AI-generated:** the VTS schedule loader (`src/sotonship26/data/vts.py`, `tests/test_vts.py`)
  was written by Claude Code (Edward's session) on Fri 16 Oct 2026. Keanu's Claude Code research
  desk compiled `ship_capacity.csv` from the public sources cited on each row.
- **AI-generated:** `src/sotonship26/data/dft.py` and `tests/test_dft.py` were written by Claude
  Code (Edward's session) on Fri 16 Oct 2026.
- **AI-generated:** the learning and evaluation code (`src/sotonship26/data/observed.py`,
  `data/cruise_history.py`, `uplift.py`, `uplift_model.py`, `backtest.py`, `run_backtest.py`,
  `flow_forecast.py`, `scripts/plot_flow_forecast.py`, `scripts/observed_noise.py`, their tests
  and everything in `notes/`)
  was written with Claude Code in Keanu's session on Fri 16 and Sat 17 Oct 2026. Keanu reviewed
  the method and the honest-baseline corrections (`notes/ml-walkthrough.md`).
- **AI-generated (NTIS self-skill + calibration):** the NTIS predicted-vs-actual diagnostics
  (`src/sotonship26/ntis_score.py`, `tests/test_ntis_score.py`, `notes/ntis-selfskill.md`) and
  the SOT-8 calibration harness (`src/sotonship26/calibrate.py`, `tests/test_calibrate.py`) were
  written with Claude Code in Keanu's session on Fri 16 and Sat 17 Oct 2026. The NTIS skill
  numbers are provisional, units unconfirmed, labelled "do not quote as validated NTIS skill".
  The calibration `best.json` is synthetic (`source: "synthetic"`) and gitignored; the real
  cruise calibration is blocked on the parametric simulator (SOT-10).
- **AI-generated (port freight):** the port lorry trip type, lorry route costs and the fit to DfT
  lorry counts (`freight_totals`, `freight_demand`, `modelled_lorries`, `calibrate_freight` and the
  freight parts of `build`, `cordon_od`, `modelled_aadf` and `count_point_edges` in
  `demo/traffic_model.py`), its wiring in `demo/synthetic_demo.py` and the page's freight table
  were written with Claude Code on Sat 17 Oct 2026 (SOT-24). So were the lorry day ratios and
  hourly shapes measured from WebTRIS site 19974, and the day-to-day scaling by VTS container and
  ro-ro calls (`demo/freight_days.py`, `load_freight_days`, `tests/test_freight_days.py`), which
  uses Keanu's VTS freight loader.
- **AI-generated (agents and PPO):** `demo/daysim.py`, `demo/agents.py`, `demo/buses.py`, `demo/ppo_env.py`, `demo/ppo_gpu.py`, `demo/train_ppo.py`, `demo/page_extras.py`, the vehicles, buses and learned-policy parts of `demo/page.html`, `tests/test_demo_agents_ppo.py`, `cluster/iridis/agents_ppo_*.slurm`, `cluster/iridis/demo_env.sh` and `docs/agents-and-ppo.md` were written with Claude Code on Sat 17 Oct 2026; `docs/ppo-results.md` is generated by `demo/train_ppo.py`. The PPO policy itself is trained by Stable-Baselines3 on the simulator.
- **AI-generated (PPO charts):** `demo/ppo_stats.py`, `tests/test_ppo_stats.py` and the "PPO in
  numbers" fold of `demo/page.html` (the charts, their styles and the stats wiring in
  `demo/page_extras.py`) were written by Claude Code (Edward's session) on Sat 17 Oct 2026.
- **AI-generated (observed buses):** `src/sotonship26/data/bus_lateness.py`, `scripts/bustimes.py`,
  `tests/test_bus_lateness.py` and the "Buses observed on the day" fold of `demo/page.html` were
  written by Claude Code (Edward's session) on Sat 17 Oct 2026, porting the bustimes.org pipeline
  from the parked Gangway branch (`claude/wizardly-thompson-ybdvds`, b8a77c4) onto main.
- **AI-generated (app UI and images):** the app shell, themes (including Steamship), action cards,
  `?` pop-ups and live-map styling in `demo/page.html`, and `demo/ui_variants.py` (the Story app
  with its landing page, plus the Focus, Officer and Wallboard layouts) were written by Claude Code
  (Edward's session) on Sat 17 Oct 2026. The cruise icons in `demo/assets/` (ship, life ring,
  anchor, wheel, seagull, lighthouse, captain's hat) were made with Canva's AI image generator on
  Sat 17 Oct 2026 and cut out of their white backgrounds by script.
- **AI-assisted research:** `notes/local-evidence.md` (local evidence, scale and business numbers)
  was compiled by Claude Code (Edward's session, with a research subagent) on Sat 17 Oct 2026 from
  the public sources cited on each line.
- **AI-generated (queues at bottlenecks):** the counted-road capacity and local-traffic change in `demo/traffic_model.py` (`COUNT_HEADROOM`, per-link top-up in `anchor_counts`), `demo/bus_check.py`, `demo/queue_report.py`, `cluster/iridis/bus_check.slurm`, `tests/test_demo_queues.py` and `docs/queues.md` were written with Claude Code on Sat 17 Oct 2026. The headroom is fitted to the council's July 2024 bus run times on Portswood Road (Portswood Project Baseline Data Report, Table 3-5) and its peak speeds (Table 3-10).
- **AI-generated (SUMO check):** `demo/sumo_net.py`, `demo/sumo_demand.py`, `demo/sumo_compare.py`, `cluster/iridis/sumo.slurm`, `tests/test_sumo_check.py` and `docs/sumo-check.md` were written with Claude Code on Sat 17 Oct 2026. The microsimulation itself is Eclipse SUMO 1.28.0 (EPL-2.0, the official container image) run on Iridis.
- **AI-generated (west-side counts, SOT-27):** counting each vehicle once at the count points
  (`run_day`'s `count` output, used by `flows`, `modelled_aadf` and `modelled_lorries`), the
  M271 cruise probe capped at capacity, the network repairs for the M27 eastbound through
  junction 3, the A326 northbound into M27 junction 2 and the M3 southbound lanes
  (`MISSING_LINKS`, `LANE_FIXES`), the count-point link choice at the A33 Redbridge Road, the
  refitted through share and other-trip decay, the alternating DfT and council fits in
  `build_ctx`, the lorry fit's limit of 95% port lorries at any HGV count point
  (`FREIGHT_HGV_LIMIT`), the refit of `COUNT_HEADROOM` and the `anchor_counts` skip rule after
  it (scan by the queues session), and `docs/west-side-counts.md` were written with Claude Code
  on Sat 17 Oct 2026.
- **AI-generated (queues at the bottleneck, SOT-30):** `traffic_model.Queues` (queued traffic
  waits at its route's bottleneck and loads only the links from there on), its use in `run_day`,
  `daysim.DaySim` and `ppo_gpu.py`, the M271 cruise probe on counted flow,
  `tests/test_demo_bottleneck_queues.py` and `docs/bottleneck-queues.md` were written with Claude
  Code on Sat 17 Oct 2026.
- **Existed before the event:** TODO, confirm with the organisers.
- **Who helped:** TODO.
