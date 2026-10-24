#!/bin/bash
# Bayesian oil pass-through (experiments/macro_bayes.py): tasks 0-7 are the forward-chaining test
# folds, task 8 fits on all data and computes the posterior oil-shock responses.
#   bash cluster/iridis/macro_env.sh                       # once, on a login node (adds jax, numpyro)
#   sbatch --array=0-8 cluster/iridis/macro_bayes.slurm                        # volatility follows oil
#   VOL=cdv sbatch --array=0-8 --time=02:00:00 cluster/iridis/macro_bayes.slurm  # + drifting volatility (~8 min/fold locally)
#   BAYES_CHAINS=4 sbatch --array=0-8 --cpus-per-task=4 cluster/iridis/macro_bayes.slurm   # more chains
#   .venv-nn/bin/python experiments/macro_bayes.py benchmarks   # random walk, surveys (needs data/raw/macro/)
#   .venv-nn/bin/python experiments/macro_bayes.py report       # once all tasks finish
#SBATCH --job-name=oxh-bayes
#SBATCH --partition=amd_student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=01:00:00
#SBATCH --output=slurm-%x-%A_%a.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK MKL_NUM_THREADS=$SLURM_CPUS_PER_TASK
export BAYES_CHAINS=${BAYES_CHAINS:-$SLURM_CPUS_PER_TASK}
PY=${PY:-.venv-nn/bin/python}
TASK=${SLURM_ARRAY_TASK_ID:-0}
VOL=${VOL:-oil}

echo "== task $TASK ($VOL) on $(hostname) $(date +%T)"
if [ "$TASK" -lt 8 ]; then
    $PY -u experiments/macro_bayes.py fold "$TASK" --vol "$VOL"
else
    $PY -u experiments/macro_bayes.py final --vol "$VOL"
fi
echo "== done $(date +%T)"
