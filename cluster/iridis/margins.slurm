#!/bin/bash
# The refined-product margin layer (experiments/margins.py): tasks 0-7 score fold j against the
# chain's draws (needs runs/macro/chain-J-{bayes_own,global_lin,global}.{npz,json} and fold-J.json);
# task 8 is the 2026 replay, which refits the chain's members (Bayes MCMC + networks) unless
# runs/macro/margins-replay-ens.npz is already there. Needs data/raw/ (incl. macro/ and the EIA spot
# workbook), notes/industry/ and runs/levy/rolling-*.json copied up.
#   sbatch --array=0-8 cluster/iridis/margins.slurm
# Copy runs/macro/margins-*.json back and run `uv run experiments/margins.py report`.
#SBATCH --job-name=oxh-margins
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=01:00:00
#SBATCH --output=slurm-%x-%A_%a.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK MKL_NUM_THREADS=$SLURM_CPUS_PER_TASK SLURM_CPUS_PER_TASK
export BAYES_CHAINS=${BAYES_CHAINS:-4} BAYES_WARMUP=${BAYES_WARMUP:-1000}  # the settings of macro_bayes.py --vol own
PY=${PY:-.venv-nn/bin/python}
TASK=${SLURM_ARRAY_TASK_ID:-0}

echo "== task $TASK on $(hostname) $(date +%T)"
if [ "$TASK" -lt 8 ]; then
  $PY -u experiments/margins.py fold "$TASK"
else
  $PY -u experiments/margins.py replay
fi
echo "== done $(date +%T)"
