#!/usr/bin/env bash
# Python environment for the demo scripts (forecast, agents, buses, PPO) on Iridis, in .venv-demo.
# Run once on a login node: compute nodes have no internet. Also downloads the BODS bus timetable.
#   bash cluster/iridis/demo_env.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
source scripts/hpc_env.sh

uv venv --python 3.12 .venv-demo
# torch for CUDA 12.6 runs on the A100 nodes; the rest is the demo's usual list plus SB3
uv pip install --python .venv-demo/bin/python --torch-backend cu126 \
    numpy scipy networkx pandas shapely pyproj scikit-learn gymnasium stable-baselines3 torch pytest
.venv-demo/bin/python -c "import torch, stable_baselines3, scipy, shapely, pyproj; print('torch', torch.__version__)"
.venv-demo/bin/python demo/buses.py fetch --download-only || \
    .venv-demo/bin/python demo/buses.py fetch --osm
