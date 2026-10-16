#!/bin/bash
# Train the PPO congestion policy on Iridis.
#   sbatch cluster/iridis/train.slurm --scenario streets --timesteps 500000
# Arguments after the script name go to sotonship-train. Check partitions with `sinfo -s`.
#
# PPO with an MLP policy plus PathFinder routing is CPU-bound, so this asks for cores, not a GPU.
# Uncomment the GPU lines once a model actually uses one (e.g. a learned congestion surrogate).
#SBATCH --job-name=sotonship-train
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=slurm-%x-%j.out
##SBATCH --partition=gpu
##SBATCH --gres=gpu:1
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
source scripts/hpc_env.sh
export OMP_NUM_THREADS=1  # one PathFinder per env process; avoid oversubscribing cores

uv run --no-sync python -m sotonship26
uv run --no-sync sotonship-train --n-envs "$SLURM_CPUS_PER_TASK" --out "runs/$SLURM_JOB_ID" "$@"
