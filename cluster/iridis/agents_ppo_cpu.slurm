#!/bin/bash
# Agents and PPO for the demo page, part 1 of 2 (CPU): forecast page, buses, agents, and the
# warm-start route shares PPO trains from. Part 2 (agents_ppo_gpu.slurm) trains PPO on an A100.
#   bash cluster/iridis/demo_env.sh                          # once, on a login node
#   J=$(sbatch --parsable cluster/iridis/agents_ppo_cpu.slurm)
#   sbatch --dependency=afterok:$J cluster/iridis/agents_ppo_gpu.slurm
# Needs the gitignored inputs copied up: data/cache/southampton/{network.pkl,base.json},
# data/cache/census/commute_flows.json, data/cache/dft/count_points.json and
# data/raw/cruise_schedule.csv. Extra arguments go to synthetic_demo.py.
#SBATCH --job-name=soton-agents-cpu
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=200G
#SBATCH --time=02:00:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1  # one process per core
PY=${PY:-.venv-demo/bin/python}
W=$((SLURM_CPUS_PER_TASK - 1))

echo "== tests $(date +%T)"
$PY -m pytest -q tests/test_demo_agents_ppo.py
echo "== forecast page $(date +%T)"
$PY -u demo/synthetic_demo.py --workers "$W" "$@"
echo "== bus timetable $(date +%T)"
B=data/cache/bods
if [ -f $B/gtfs_south_west.zip ] && ! [ $B/southampton_buses.json -nt $B/gtfs_south_west.zip ]; then
    $PY -u demo/buses.py fetch
fi
echo "== agents and buses $(date +%T)"
$PY -u demo/agents.py
echo "== warm-start shares $(date +%T)"
$PY -u demo/train_ppo.py prepare --workers "$W"
echo "== done $(date +%T)"
