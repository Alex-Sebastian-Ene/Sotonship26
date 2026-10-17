#!/bin/bash
# Smoke test of the whole agents + PPO pipeline in a few minutes: two forecast days, one agent
# day, a short CPU training run and a tiny evaluation. Writes to demo/out/smoke*.
#   sbatch cluster/iridis/agents_ppo_smoke.slurm
#SBATCH --job-name=soton-agents-smoke
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=48G
#SBATCH --time=00:45:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
PY=${PY:-.venv-demo/bin/python}
W=$((SLURM_CPUS_PER_TASK - 1))

echo "== tests $(date +%T)"
$PY -m pytest -q tests/test_demo_agents_ppo.py
echo "== forecast $(date +%T)"
$PY -u demo/synthetic_demo.py --days 2 --n 2 --n-bg 2 --whatif-days 0 --advise-days 0 \
    --workers "$W" --out demo/out/demo.html
if [ -f data/cache/bods/gtfs_south_west.zip ]; then $PY -u demo/buses.py fetch; fi
echo "== agents $(date +%T)"
$PY -u demo/agents.py --everyday 1500 --cruise-rate 0.1 --n-busiest 1
echo "== prepare $(date +%T)"
$PY -u demo/train_ppo.py prepare --workers "$W"
echo "== train $(date +%T)"
$PY -u demo/train_ppo.py train --n-envs 8 --timesteps 1920 --n-steps 120 --batch-size 240 \
    --out runs/ppo/smoke --cpu
echo "== evaluate $(date +%T)"
$PY -u demo/train_ppo.py evaluate --model runs/ppo/smoke/model.zip --workers "$W" --n-days 1 \
    --n-seen-dates 1 --n-test-dates 2 --n-advise 1 --n-page 1
$PY -u demo/page_extras.py
ls -la demo/out
echo "== done $(date +%T)"
