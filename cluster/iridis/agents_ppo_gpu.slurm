#!/bin/bash
# Agents and PPO for the demo page, part 2 of 2 (A100): train PPO, test it against do nothing, the
# rule and the ship-timing advisor, and put agents, buses and PPO into the page.
#   sbatch --dependency=afterok:<part 1 job> cluster/iridis/agents_ppo_gpu.slurm
#   TIMESTEPS=600000 sbatch cluster/iridis/agents_ppo_gpu.slurm      # more training
#   GPU_ENVS=128 TIMESTEPS=5000000 TAG=gpu sbatch cluster/iridis/agents_ppo_gpu.slurm
# By default the simulator runs in one process per CPU core and only the policy updates use the
# GPU. With GPU_ENVS the simulator runs on the GPU too (demo/ppo_gpu.py: that many sampled days
# per sparse product, about 40 times faster) and the CPU cores draw the days. TAG writes the
# results next to the default ones (demo/out/ppo_TAG.json, docs/ppo-results-TAG.md) and leaves
# the page alone.
#SBATCH --job-name=soton-ppo-gpu
#SBATCH --partition=a100
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=96G
#SBATCH --time=05:00:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
PY=${PY:-.venv-demo/bin/python}
W=$((SLURM_CPUS_PER_TASK - 1))
RUN=runs/ppo/${SLURM_JOB_ID}
EXTRA=()
if [ "${GPU_ENVS:-0}" -gt 0 ]; then EXTRA=(--gpu-envs "$GPU_ENVS"); fi
TAG=${TAG:-}

nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
$PY -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
echo "== train $(date +%T)"
$PY -u demo/train_ppo.py train --n-envs "$W" "${EXTRA[@]}" --timesteps "${TIMESTEPS:-400000}" \
    --out "$RUN"
echo "== evaluate $(date +%T)"
$PY -u demo/train_ppo.py evaluate --model "$RUN/model.zip" --workers "$W" \
    --json "demo/out/ppo${TAG:+_$TAG}.json" --doc "docs/ppo-results${TAG:+-$TAG}.md"
if [ -z "$TAG" ]; then
    echo "== page $(date +%T)"
    $PY -u demo/page_extras.py
fi
echo "== done $(date +%T)"
