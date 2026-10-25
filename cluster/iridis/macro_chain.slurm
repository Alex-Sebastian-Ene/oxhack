#!/bin/bash
# The knock-on chain (experiments/macro_chain.py): task j fits every member on fold j and simulates
# all three oil modes. Needs data/raw/ (incl. macro/) and runs/levy/rolling-*.json copied up.
#   bash cluster/iridis/macro_env.sh                                   # once, on a login node
#   sbatch --array=0-7 cluster/iridis/macro_chain.slurm                # 5 networks per variant
#   CHAIN_SEEDS=20 CHAIN_TAG=s20 sbatch --array=0-7 --time=06:00:00 cluster/iridis/macro_chain.slurm
#   MEMBERS="global_tcn" sbatch --array=0-7 cluster/iridis/macro_chain.slurm   # one member only
# Copy runs/macro/chain-*.{npz,json} back and run `macro_chain.py report` (needs runs/macro/fold-*.json).
#SBATCH --job-name=oxh-chain
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=03:00:00
#SBATCH --output=slurm-%x-%A_%a.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK MKL_NUM_THREADS=$SLURM_CPUS_PER_TASK SLURM_CPUS_PER_TASK
export BAYES_CHAINS=${BAYES_CHAINS:-4} BAYES_WARMUP=${BAYES_WARMUP:-1000}  # the settings of macro_bayes.py --vol own
PY=${PY:-.venv-nn/bin/python}
TASK=${SLURM_ARRAY_TASK_ID:-0}

echo "== task $TASK seeds=${CHAIN_SEEDS:-default} tag=${CHAIN_TAG:-} members=${MEMBERS:-all} on $(hostname) $(date +%T)"
# shellcheck disable=SC2086
$PY -u experiments/macro_chain.py fold "$TASK" ${MEMBERS:-}
echo "== done $(date +%T)"
