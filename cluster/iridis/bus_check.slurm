#!/bin/bash
# Queue calibration check (docs/queues.md): builds the forecast page, then runs the Portswood
# Road bus check (demo/bus_check.py) on a term-time weekday, the same weekday without the
# university-term uplift (like the council's July 2024 survey), and a weekday with the Portswood
# Road permits. Prints the count fits and corridor-hours at risk (demo/queue_report.py).
#   sbatch cluster/iridis/bus_check.slurm
# Needs the inputs agents_ppo_cpu.slurm needs, plus data/cache/bods/southampton_buses.json.
#SBATCH --job-name=soton-bus-check
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=200G
#SBATCH --time=01:30:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
PY=${PY:-.venv-demo/bin/python}
N=${N:-16}
mkdir -p demo/out/check

echo "== forecast page $(date +%T)"
$PY -u demo/synthetic_demo.py --workers $((SLURM_CPUS_PER_TASK - 1)) "$@" | tee demo/out/check/build.log
for spec in "2026-11-16 term" "2026-11-16 july --uni-term 1" "2026-10-21 permits"; do
    set -- $spec
    echo "== bus check $1 $2 $(date +%T)"
    $PY -u demo/bus_check.py --date "$1" --n "$N" --workers "$N" --json "demo/out/check/bus_$2.json" "${@:3}"
done
echo "== report $(date +%T)"
$PY -u demo/queue_report.py demo/out/check
echo "== done $(date +%T)"
