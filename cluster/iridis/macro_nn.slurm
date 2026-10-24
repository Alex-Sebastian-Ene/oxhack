#!/bin/bash
# Deep ensemble for the knock-on chain (experiments/macro_nn.py): tasks 0-7 are the forward-chaining
# test folds, task 8 fits on all data and computes the oil-shock responses.
#   bash cluster/iridis/macro_env.sh                       # once, on a login node
#   sbatch --array=0-8 cluster/iridis/macro_nn.slurm
#   .venv-nn/bin/python experiments/macro_nn.py report     # once all tasks finish
#SBATCH --job-name=oxh-macro
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --output=slurm-%x-%A_%a.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK MKL_NUM_THREADS=$SLURM_CPUS_PER_TASK
PY=${PY:-.venv-nn/bin/python}
TASK=${SLURM_ARRAY_TASK_ID:-0}

echo "== task $TASK on $(hostname) $(date +%T)"
if [ "$TASK" -lt 8 ]; then
    $PY -u experiments/macro_nn.py fold "$TASK"
else
    $PY -u experiments/macro_nn.py final
fi
echo "== done $(date +%T)"
