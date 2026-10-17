#!/bin/bash
# Rebuild the cruise-day forecast page on Iridis: the WebTRIS backtest (learned M271 uplift), the
# simulator fit to it, then the paired Monte Carlo forecast, what-ifs and ship-timing advice.
#   sbatch cluster/iridis/forecast.slurm                 # defaults below
#   sbatch cluster/iridis/forecast.slurm --n 60          # extra arguments go to synthetic_demo.py
# Needs the gitignored data/ copied up first (data/cache/{southampton,census,dft,webtris,wikidata},
# data/cache/bank_holidays.json, data/raw/). Warm uv's cache on a login node first (compute nodes
# run offline). Check partitions with `sinfo -s`.
#SBATCH --job-name=soton-forecast
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=200G
#SBATCH --time=02:00:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
source scripts/hpc_env.sh
export UV_OFFLINE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1  # one process per core
W=$((SLURM_CPUS_PER_TASK - 1))

UV=(uv run --no-project --python 3.12 --with numpy --with scipy --with networkx --with pandas
    --with shapely --with pyproj --with scikit-learn)
echo "== backtest $(date +%T)"
OMP_NUM_THREADS="$SLURM_CPUS_PER_TASK" "${UV[@]}" python demo/webtris_backtest.py
echo "== smoke test $(date +%T)"
"${UV[@]}" python -u demo/synthetic_demo.py --days 1 --n 2 --n-fit 2 --whatif-days 0 \
    --advise-days 0 --workers "$W" --out demo/out/smoke.html
echo "== full run $(date +%T)"
"${UV[@]}" python -u demo/synthetic_demo.py --n 30 --whatif-days 6 --advise-days 10 \
    --n-advise 12 --n-fit 8 --workers "$W" --out demo/out/demo.html "$@"
echo "== done $(date +%T)"
