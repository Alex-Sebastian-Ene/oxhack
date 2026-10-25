#!/bin/bash
# Global one-step network (experiments/macro_global.py): tasks 0-7 are the forward-chaining test folds.
#   bash cluster/iridis/macro_env.sh                                     # once, on a login node
#   sbatch --array=0-7 cluster/iridis/macro_global.slurm                 # what-if -> runs/macro/global-fold-*.json
#   CMD=forecast sbatch --array=0-7 cluster/iridis/macro_global.slurm    # both oil modes -> global-forecast-fold-*.json
#   # on the laptop (downloads the SPF files): uv run experiments/macro_global.py benchmarks, then report
#SBATCH --job-name=oxh-global
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=01:30:00
#SBATCH --output=slurm-%x-%A_%a.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK MKL_NUM_THREADS=$SLURM_CPUS_PER_TASK
PY=${PY:-.venv-nn/bin/python}
TASK=${SLURM_ARRAY_TASK_ID:-0}
CMD=${CMD:-fold}

echo "== task $TASK ($CMD) on $(hostname) $(date +%T)"
$PY -u experiments/macro_global.py "$CMD" "$TASK"
echo "== done $(date +%T)"
