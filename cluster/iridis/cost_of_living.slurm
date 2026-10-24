#!/bin/bash
# Cost-of-living basket model (experiments/cost_of_living.py): one array task per fit.
# Tasks 0-2 are event-2026, event-2022 and final; tasks 3-10 are the forward-chaining folds 0-7.
# Tasks 11-21 are the same fits with grain and urea prices as food drivers (COL_FOOD=1).
#   bash cluster/iridis/cost_of_living_env.sh                  # once, on a login node
#   sbatch --array=0-21 cluster/iridis/cost_of_living.slurm    # 0-10 for the base model only
#   .venv-col/bin/python experiments/cost_of_living.py report  # once all tasks finish
# Needs data/raw/ (the cached downloads) and runs/levy/rolling-*.json (the daily Lévy fits) copied in.
#SBATCH --job-name=oxh-col
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=03:00:00
#SBATCH --output=slurm-%x-%A_%a.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK MKL_NUM_THREADS=$SLURM_CPUS_PER_TASK
PY=${PY:-.venv-col/bin/python}
NAMES=(event-2026 event-2022 final fold-0 fold-1 fold-2 fold-3 fold-4 fold-5 fold-6 fold-7)
TASK=${SLURM_ARRAY_TASK_ID:-0}
NAME=${NAMES[$((TASK % 11))]}
export COL_FOOD=$((TASK >= 11 ? 1 : 0))
export COL_SAMPLES=${COL_SAMPLES:-1000}  # draws per chain; 500 left one fold just under ESS 100

echo "== $NAME (food drivers: $COL_FOOD) on $(hostname) $(date +%T)"
$PY -u experiments/cost_of_living.py fit "$NAME"
echo "== done $(date +%T)"
