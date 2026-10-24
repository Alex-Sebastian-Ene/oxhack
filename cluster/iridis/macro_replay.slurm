#!/bin/bash
# The 2026 closure replay and scenario tables (experiments/macro_chain.py replay): fits every member
# on months before 2026-02 and simulates from it. Task 0: the recommended 3 members (outputs tagged
# 3m); task 1: every available member. Needs notes/flow-premium.csv and notes/industry/ copied up.
#   sbatch --array=0-1 cluster/iridis/macro_replay.slurm
# Copy notes/chain-replay-2026*.md and notes/chain-scenarios*.csv back.
#SBATCH --job-name=oxh-replay
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=02:00:00
#SBATCH --output=slurm-%x-%A_%a.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK MKL_NUM_THREADS=$SLURM_CPUS_PER_TASK SLURM_CPUS_PER_TASK
export BAYES_CHAINS=${BAYES_CHAINS:-4} BAYES_WARMUP=${BAYES_WARMUP:-1000}  # the settings of macro_bayes.py --vol own
PY=${PY:-.venv-nn/bin/python}
TASK=${SLURM_ARRAY_TASK_ID:-0}
if [ "$TASK" -eq 0 ]; then
    export CHAIN_MEMBERS=bayes_own,global_lin,global CHAIN_TAG=3m
fi

echo "== replay task $TASK members=${CHAIN_MEMBERS:-all} tag=${CHAIN_TAG:-} on $(hostname) $(date +%T)"
$PY -u experiments/macro_chain.py replay
echo "== done $(date +%T)"
