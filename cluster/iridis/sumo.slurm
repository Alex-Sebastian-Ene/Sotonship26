#!/bin/bash
# SUMO microsimulation of sampled cruise days (demo/sumo_*.py, docs/sumo-check.md): one array task
# per day; each builds the day's trips from the forecast model, runs SUMO microscopic and
# mesoscopic side by side, then compares them with the macro model.
#   Once, on a login node (compute nodes are offline):
#     module load apptainer
#     apptainer pull sumo.sif docker://ghcr.io/eclipse-sumo/sumo:latest     # SUMO 1.28.0
#     apptainer build --sandbox sumo_sandbox sumo.sif   # no fusermount on Iridis to mount a .sif
#     .venv-demo/bin/python demo/sumo_net.py fetch
#     SUMO_CONTAINER=$PWD/sumo_sandbox .venv-demo/bin/python demo/sumo_net.py build
#   then: sbatch cluster/iridis/sumo.slurm          (SCALE=0.25 for a quick look)
# Needs the gitignored inputs agents_ppo_cpu.slurm lists, data/cache/bods/southampton_buses.json
# and, for the M271 check, data/cache/webtris/19974_*.csv. The pip eclipse-sumo wheels crash at
# start-up on Iridis' RHEL 8 nodes, hence the container; sumolib comes from pip.
#SBATCH --job-name=soton-sumo
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=20
#SBATCH --mem=96G
#SBATCH --time=12:00:00
#SBATCH --array=0-1
#SBATCH --output=slurm-%x-%A_%a.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
module load apptainer
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export SUMO_CONTAINER=${SUMO_CONTAINER:-/scratch/$USER/sumo-sif/sumo_sandbox}
PY=${PY:-.venv-demo/bin/python}
DAYS=(${DAYS:-2026-11-16 2026-11-07})
DAY=${DAYS[${SLURM_ARRAY_TASK_ID:-0}]}
SCALE=${SCALE:-1.0}
OUT=${OUT:-runs/sumo}
MODES=${MODES:-"micro meso"}
SIM_THREADS=${SIM_THREADS:-1}  # micro: SUMO's parallel simulation (--threads)
SUMO="apptainer exec -B /scratch,/iridisfs $SUMO_CONTAINER sumo"

echo "== demand $DAY scale $SCALE $(date +%T)"
$PY -u demo/sumo_demand.py --date "$DAY" --scale "$SCALE" --out "$OUT" --threads 8 \
    --sim-threads "$SIM_THREADS"
R=$OUT/$DAY
echo "== SUMO $MODES $(date +%T)"
for M in $MODES; do
    $SUMO -c $R/$M.sumocfg > $R/$M.out 2>&1 &
    eval "PID_$M=$!"
done
for M in $MODES; do
    P=PID_$M
    wait ${!P} && echo "$M done $(date +%T)" || echo "$M failed"
    tail -25 $R/$M.out
done
echo "== compare $(date +%T)"
$PY -u demo/sumo_compare.py --date "$DAY" --out "$OUT" --modes "${MODES// /,}"
echo "== done $(date +%T)"
