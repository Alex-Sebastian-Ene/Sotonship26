#!/usr/bin/env bash
# Build the uv environment on Linux: Iridis (NVIDIA), an AMD ROCm machine, or CPU only.
#
#   bash scripts/setup_env.sh          # pick the PyTorch backend from the GPUs on this machine
#   bash scripts/setup_env.sh cu126    # or name it: cpu | cu126 | cu130 | rocm
#
# HPC login nodes usually have no GPU, so there you name the backend the compute nodes need.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/hpc_env.sh

if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

detect() {
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
        local cc driver_cuda
        cc=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | sort -V | head -n1)
        driver_cuda=$(nvidia-smi | grep -oP 'CUDA Version: \K[0-9]+' || echo 0)
        # cu130 needs Turing (7.5) or newer and a CUDA 13 driver; otherwise cu126.
        if awk -v c="$cc" 'BEGIN { exit !(c >= 7.5) }' && [ "$driver_cuda" -ge 13 ]; then
            echo cu130
        else
            echo cu126
        fi
    elif [ -e /dev/kfd ] || command -v rocminfo >/dev/null 2>&1; then
        echo rocm
    elif [[ "$(hostname)" == login* ]]; then
        echo "No GPU on this login node: rerun with cu126, cu130 or rocm for the compute nodes." >&2
        return 1
    else
        echo cpu
    fi
}

backend="${1:-$(detect)}"
case "$backend" in
    cpu | cu126 | cu130 | rocm) ;;
    *) echo "Unknown backend '$backend' (expected cpu, cu126, cu130 or rocm)" >&2; exit 1 ;;
esac

echo "$backend" > .torch-backend
uv sync --locked --extra "$backend"
uv run --no-sync python -m sotonship26
echo
echo "Ready ($backend). Run commands with:  uv run --extra $backend <command>"
echo "or activate the environment:          source .venv/bin/activate"
