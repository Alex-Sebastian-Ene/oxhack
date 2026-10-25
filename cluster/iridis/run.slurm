#!/bin/bash
# One task of a cluster/iridis/run.sh submission: task i runs line i+1 of jobs.txt, which holds the
# arguments to python (e.g. "experiments/sector_global.py fold 3 --set goods"). run.sh sets the
# job name, array, CPUs, memory and time on the command line; the values here are fallbacks.
#SBATCH --job-name=oxh-run
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
LINE=$(sed -n "$((TASK + 1))p" jobs.txt)
[ -n "$LINE" ] || { echo "no line $((TASK + 1)) in jobs.txt"; exit 1; }
eval "set -- $LINE"

echo "== task $TASK on $(hostname) $(date +%T): python $LINE"
"$PY" -u "$@"
echo "== done $(date +%T)"
