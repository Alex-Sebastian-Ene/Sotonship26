#!/bin/bash
# Agents and PPO for the demo page, part 2 of 2 (A100): train PPO, test it against do nothing, the
# rule and the ship-timing advisor, and put agents, buses and PPO into the page.
#   sbatch --dependency=afterok:<part 1 job> cluster/iridis/agents_ppo_gpu.slurm
#   TIMESTEPS=600000 sbatch cluster/iridis/agents_ppo_gpu.slurm      # more training
# The simulator runs in one process per CPU core; the policy updates run on the GPU.
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

nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
$PY -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
echo "== train $(date +%T)"
$PY -u demo/train_ppo.py train --n-envs "$W" --timesteps "${TIMESTEPS:-400000}" --out "$RUN"
echo "== evaluate $(date +%T)"
$PY -u demo/train_ppo.py evaluate --model "$RUN/model.zip" --workers "$W"
echo "== page $(date +%T)"
$PY -u demo/page_extras.py
echo "== done $(date +%T)"
