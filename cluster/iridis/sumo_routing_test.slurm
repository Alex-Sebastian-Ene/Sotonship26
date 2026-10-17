#!/bin/bash
# Why does SUMO gridlock at the forecast's demand? One weekday (16 Nov) at 75% of the demand, with
# rerouting off (each vehicle keeps the route it gets when it enters), on two networks without
# roundabout signals: A) the main roads only, as in the other runs; B) with residential streets
# too, where zone trips can also start and end. Micro and meso for each, on one node.
#   .venv-demo/bin/python demo/sumo_net.py fetch --residential           # login node, once
#   SUMO_CONTAINER=... .venv-demo/bin/python demo/sumo_net.py no-ring-signals --residential
#   sbatch --nice=10000 cluster/iridis/sumo_routing_test.slurm
# It gives way to the team: if another of this user's jobs waits on the per-user node limit for
# two minutes, the SUMO runs are stopped (their outputs up to then are compared) and the node is
# freed.
#SBATCH --job-name=soton-sumo-test
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=10:00:00
#SBATCH --output=slurm-%x-%j.out
set -uo pipefail
cd "$SLURM_SUBMIT_DIR"
module load apptainer
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export SUMO_CONTAINER=${SUMO_CONTAINER:-/scratch/$USER/sumo-sif/sumo_sandbox}
PY=${PY:-.venv-demo/bin/python}
DAY=${DAY:-2026-11-16}
SCALE=${SCALE:-0.75}
SUMO="apptainer exec -B /scratch,/iridisfs $SUMO_CONTAINER sumo"
declare -A NET=([a]=data/cache/sumo/southampton_no_ring_signals.net.xml.gz
                [b]=data/cache/sumo/southampton_res_no_ring_signals.net.xml.gz)
PIDS=()

for V in a b; do
    echo "== demand $V $(date +%T)"
    $PY -u demo/sumo_demand.py --date "$DAY" --scale "$SCALE" --out runs/sumo-test-$V \
        --net "${NET[$V]}" --no-reroute || exit 1
done
echo "== SUMO $(date +%T)"
for V in a b; do
    for M in micro meso; do
        R=runs/sumo-test-$V/$DAY
        $SUMO -c $R/$M.sumocfg > $R/$M.out 2>&1 &
        PIDS+=($!)
    done
done

# give way to the team's jobs (same user, same node limit)
alive() { for p in "${PIDS[@]}"; do kill -0 "$p" 2>/dev/null && return 0; done; return 1; }
strikes=0
while alive; do
    sleep 60
    if squeue -u "$USER" -h -t PD -o "%j %r" | grep -v soton-sumo | grep -q QOSMaxNodePerUserLimit; then
        strikes=$((strikes + 1))
    else
        strikes=0
    fi
    if [ $strikes -ge 2 ]; then
        echo "== a team job is waiting for a node: stopping SUMO at $(date +%T)"
        kill "${PIDS[@]}" 2>/dev/null
        break
    fi
done
wait
echo "== SUMO finished or stopped $(date +%T)"
for V in a b; do
    $PY -u demo/sumo_compare.py --date "$DAY" --out runs/sumo-test-$V --net "${NET[$V]}" \
        > runs/sumo-test-$V/$DAY/compare.out 2>&1
    grep -E "^### |stopped at|Delay on the network|Spearman|^\| (busy|jammed)" \
        runs/sumo-test-$V/$DAY/compare.md
done
echo "== done $(date +%T)"
