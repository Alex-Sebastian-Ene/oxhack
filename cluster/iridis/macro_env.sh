#!/usr/bin/env bash
# Python environment for experiments/macro_nn.py on Iridis, in .venv-nn (CPU PyTorch is enough for
# networks this small). Run once on a login node; compute nodes have no internet, so also copy
# data/raw/macro/ up from the laptop (macro_data.py caches every download there).
#   bash cluster/iridis/macro_env.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
source scripts/hpc_env.sh

uv venv --python 3.12 .venv-nn
uv pip install --python .venv-nn/bin/python --index-url https://download.pytorch.org/whl/cpu torch
uv pip install --python .venv-nn/bin/python "numpy>=1.26" "pandas>=2.1" "scipy>=1.11" "xlrd>=2.0"
uv pip install --python .venv-nn/bin/python "jax>=0.4.30" "numpyro>=0.15"  # experiments/macro_bayes.py
.venv-nn/bin/python -c "import torch, numpy, pandas, scipy, numpyro; print('torch', torch.__version__, 'numpyro', numpyro.__version__)"
