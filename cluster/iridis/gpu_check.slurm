#!/bin/bash
# Five-minute job that checks the PyTorch backend sees the GPU on an Iridis compute node.
#   sbatch cluster/iridis/gpu_check.slurm
# Partition names differ between Iridis systems: list them with `sinfo -s` and edit below.
#SBATCH --job-name=sotonship-gpucheck
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:05:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
source scripts/hpc_env.sh
nvidia-smi || rocm-smi || true
# Built on the login node by scripts/setup_env.sh; compute nodes may have no internet, so no sync.
uv run --no-sync python -m sotonship26
