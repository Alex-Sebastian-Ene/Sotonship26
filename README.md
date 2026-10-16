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
| Southampton VTS cruise schedule: the XML feed behind the [cruise ship schedule page](https://www.southamptonvts.co.uk/live_information/shipping_movements_and_cruise_ship_schedule/cruise_ship_schedule/) | Ship calls, fetched live by `data/vts.py` and cached in `data/raw/vts/`, not committed | At run time; `collected_at` on every row (first pull 16 Oct 2026) | © ABP, all rights reserved; we don't redistribute it |
| Ship lower-berth capacity, 22 ships (Wikipedia, cruise line and cruisemapper pages; URL per row) | `passengers` per call, `src/sotonship26/data/ship_capacity.csv` | 16 Oct 2026 | Facts with the source cited on each row |
| UKHO ADMIRALTY UK Tidal API (Discovery tier, key in `UKHO_API_KEY`) | High/low water predictions | TODO | TODO |
| OpenStreetMap via osmnx | Walking network around the terminals | TODO | ODbL |
| Bathymetry + water polygon for Southampton Water | Replace the synthetic lattice | TODO | TODO |
| Footway widths, pedestrian counts on turnaround days | Calibrate capacities | TODO | TODO |
| Red Funnel / Hythe ferry timetables, leisure-craft activity | Waterway demand | TODO | TODO |

## Provenance

- **AI-generated:** the project scaffold (`pyproject.toml` backend extras, `src/`, `tests/`,
  `scripts/`, `cluster/`, `configs/`, this README) was generated with Claude Code on
  Fri 16 Oct 2026.
- **AI-generated:** the VTS schedule loader (`src/sotonship26/data/vts.py`, `tests/test_vts.py`)
  was written by Claude Code (Edward's session) on Fri 16 Oct 2026. Keanu's Claude Code research
  desk compiled `ship_capacity.csv` from the public sources cited on each row.
- **Existed before the event:** TODO, confirm with the organisers.
- **Who helped:** TODO.
