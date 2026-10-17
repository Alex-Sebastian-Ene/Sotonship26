# Sotonship26

We help Southampton City Council's events team plan cruise turnaround days by forecasting, with
probabilities, where passengers will overload the streets around the terminals and where ferries and
leisure craft will bunch up against the clear channel kept for large ships in Southampton Water. The
inputs are the cruise schedule, UKHO tide predictions and an autorouting-style congestion model run
over both the street network and the waterway.

## How it fits together

```
cruise schedule ─┐                        ┌─ street graph (OSM walking network)
UKHO tides ──────┼─► demand per 15-min bin ┼─► PathFinder negotiated-congestion routing
ferry timetable ─┘   (sampled per scenario)└─ waterway lattice minus the moving clear channel
                                   │
                   Monte Carlo over many sampled days
                                   ▼
          P(overload) per street segment / water cell per time bin
          + where craft are held waiting to cross the channel
                                   │
              RL agent (PPO) learns metering and steering levers
```

| Module | What it does |
| --- | --- |
| `data/cruise.py` | Loads the cruise schedule CSV (`ship, terminal, arrival, departure, passengers`) |
| `data/tides.py` | ADMIRALTY UK Tidal API client (`UKHO_API_KEY`) and tide height interpolation |
| `data/streets.py` | OSM walking network around the terminals with per-edge capacity |
| `data/waterway.py` | Southampton Water as a lattice, gated by depth at the predicted tide |
| `demand/` | Passenger turnaround flows, ferry runs, leisure-craft trips per time bin |
| `routing/pathfinder.py` | PathFinder (McMurchie & Ebeling) rip-up-and-reroute congestion negotiation |
| `routing/clear_channel.py` | The moving exclusion box ahead of large ships |
| `forecast/` | Monte Carlo over sampled days → overload probabilities |
| `rl/env.py` | Gymnasium env: steer edges and meter demand to cut overload |
| `synthetic.py` | Small street and waterway scenarios so everything runs before real data |

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
| UKHO ADMIRALTY UK Tidal API (Discovery tier, key in `UKHO_API_KEY`) | High/low water predictions | TODO | TODO |
| OpenStreetMap via osmnx | Walking network around the terminals | TODO | ODbL |
| Bathymetry + water polygon for Southampton Water | Replace the synthetic lattice | TODO | TODO |
| Footway widths, pedestrian counts on turnaround days | Calibrate capacities | TODO | TODO |
| Red Funnel / Hythe ferry timetables, leisure-craft activity | Waterway demand | TODO | TODO |
| ONS Census 2021 ODWP01EW, location of usual residence and place of work (MSOA), [Nomis bulk download](https://www.nomisweb.co.uk/sources/census_2021_od) | Demo: commuters into and out of the study area, where they live or work, which gateway they use (`demo/external_data.py`, `data/cache/census`, not committed). Census day was 21 Mar 2021, in lockdown | 16 Oct 2026 | Open Government Licence v3.0 |
| ONS Census 2021 method used to travel to work by distance travelled, per local authority ([census API](https://api.beta.ons.gov.uk/v1/population-types/UR/census-observations?area-type=ltla&dimensions=transport_to_workplace_12a,workplace_travel_10a)) | Demo: share of each commuter flow driving a car or van | 16 Oct 2026 | Open Government Licence v3.0 |
| ONS MSOA (Dec 2021) population-weighted centroids V2, Open Geography Portal | Demo: placing each MSOA inside or outside the study area | 16 Oct 2026 | Open Government Licence v3.0; contains OS data © Crown copyright and database right |
| DfT road traffic statistics, AADF per count point ([dft_traffic_counts_aadf.zip](https://roadtraffic.dft.gov.uk/downloads), published Jun 2026, 2025 counts) | Demo: traffic crossing each county gateway (count point on the gateway road), less census commuters and visitors, split 30% through traffic and 70% other trips to the area's zones; scale for everything crossing the edge of the area fitted to 10 count points and checked at 2 more (M271, A33 Redbridge Road, A35 Redbridge Causeway, A33 Millbrook Road and The Avenue, Itchen Bridge, Northam Bridge, A335, M27, M3) (`data/cache/dft`, not committed) | 16 Oct 2026 | Open Government Licence v3.0 |

**ABP attribution.** Cruise schedule data, current and archived, © Associated British Ports
(Southampton VTS). It is used for personal reference with ABP acknowledged, as ABP's terms allow.
Raw pages and call lists are never committed, and only aggregates are published.

**Limits of the cruise backtest.** Past calls are provisional plans captured on four dates, not
actual berthings. Days no capture covers (Jul 2024, Jan to Aug 2025) are left out rather than
counted as non-cruise days. The traffic is one motorway sensor (M271 northbound), 4 to 7 km from
the terminals. Most of the model's gain over the baselines comes from the calendar: adding ship
data improves it by about 4% a day (not significant) and 2% per 15 minutes.

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
- **AI-generated:** `demo/external_data.py`, the census commuter gateways (`census_od`), through
  traffic and other county trips from DfT gateway counts (`cordon_od`), the DfT count fit
  (`calibrate_external`) and the motorway repairs (`repair_motorways`) in `demo/traffic_model.py`
  were written with Claude Code on 16-17 Oct 2026.
- **Existed before the event:** TODO, confirm with the organisers.
- **Who helped:** TODO.
