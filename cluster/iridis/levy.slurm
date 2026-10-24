#!/bin/bash
# Learned-Lévy GARCH model (experiments/levy_fourier.py) on Iridis, one array task per run:
# task 0 is the fixed split, tasks 1-29 are the rolling refits for 1998-2026.
#   bash cluster/iridis/levy_env.sh                        # once, on a login node
#   sbatch --array=0-29 cluster/iridis/levy.slurm
#   FAMILY=iid sbatch --array=0-29 cluster/iridis/levy.slurm  # the same with constant sigma
#   .venv-levy/bin/python experiments/levy_fourier.py report   # on the login node once all finish
# PATHS (default 20000) sets the simulated paths per forecast origin; FAMILY is garch or iid.
#SBATCH --job-name=oxh-levy
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=03:00:00
#SBATCH --output=slurm-%x-%A_%a.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK OPENBLAS_NUM_THREADS=$SLURM_CPUS_PER_TASK
PY=${PY:-.venv-levy/bin/python}
PATHS=${PATHS:-20000}
FAMILY=${FAMILY:-garch}
TASK=${SLURM_ARRAY_TASK_ID:-0}

echo "== task $TASK ($FAMILY) on $(hostname) $(date +%T)"
if [ "$TASK" -eq 0 ]; then
    $PY -u experiments/levy_fourier.py check
    $PY -u experiments/levy_fourier.py fit --paths "$PATHS" --family "$FAMILY"
else
    $PY -u experiments/levy_fourier.py rolling $((1997 + TASK)) --paths "$PATHS" --family "$FAMILY"
fi
echo "== done $(date +%T)"
