#!/usr/bin/env bash
# Python environment for experiments/levy_fourier.py on Iridis, in .venv-levy. Run once on a login
# node (compute nodes have no internet). Copy data/raw/DCOILBRENTEU.csv up from the laptop so both
# sides use the same data vintage; this only fetches it if it is missing.
#   bash cluster/iridis/levy_env.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
source scripts/hpc_env.sh

uv venv --python 3.12 .venv-levy
uv pip install --python .venv-levy/bin/python "numpy>=1.26" "scipy>=1.11" "pandas>=2.1"
if [ ! -f data/raw/DCOILBRENTEU.csv ]; then
    mkdir -p data/raw
    curl -sSfL -o data/raw/DCOILBRENTEU.csv "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"
fi
.venv-levy/bin/python -c "import numpy, scipy, pandas; print('numpy', numpy.__version__, 'scipy', scipy.__version__)"
