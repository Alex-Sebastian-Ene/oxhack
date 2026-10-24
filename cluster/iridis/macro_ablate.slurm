#!/bin/bash
# Diagnostics for the knock-on ensemble (experiments/macro_nn.py VARIANTS): task = variant x fold.
# The v1 set is 7 variants x 8 folds = tasks 0-55; pass another list in RUN_VARIANTS, e.g.
#   sbatch --array=0-55 cluster/iridis/macro_ablate.slurm
#   RUN_VARIANTS="v2_all v2_no_fuel v2_no_pipeline v2_no_drivers v2_no_ais_pipeline" \
#     sbatch --array=0-39 cluster/iridis/macro_ablate.slurm
#SBATCH --job-name=oxh-macro-abl
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=6G
#SBATCH --time=02:00:00
#SBATCH --output=slurm-%x-%A_%a.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK MKL_NUM_THREADS=$SLURM_CPUS_PER_TASK
PY=${PY:-.venv-nn/bin/python}
read -r -a VARIANTS <<< "${RUN_VARIANTS:-full no_oil_path no_ais no_market_signals lookahead shuffled_targets window_12}"
TASK=${SLURM_ARRAY_TASK_ID:-0}
VARIANT=${VARIANTS[$((TASK / 8))]}
FOLD=$((TASK % 8))

echo "== $VARIANT fold $FOLD on $(hostname) $(date +%T)"
$PY -u experiments/macro_nn.py ablate "$VARIANT" "$FOLD"
echo "== done $(date +%T)"
