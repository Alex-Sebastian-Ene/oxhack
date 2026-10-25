#!/bin/bash
# Python environment for experiments/cost_of_living.py on Iridis, in .venv-col (no PyTorch needed).
#   bash cluster/iridis/cost_of_living_env.sh    # once, on a login node, from the run folder
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"  # uv's default install location
# A uv-managed Python on scratch: compute nodes don't have the login node's /usr/bin/python3.12.
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/scratch/$USER/.local/share/uv/python}"
rm -rf .venv-col
uv venv --python 3.12 --python-preference only-managed .venv-col
uv pip install --python .venv-col/bin/python "numpy>=1.26" "pandas>=2.1" "scipy>=1.11" "xlrd>=2.0" "openpyxl>=3.1" \
    "jax>=0.4.30" "numpyro>=0.15"
.venv-col/bin/python -c "import jax, numpyro, scipy, pandas; print('jax', jax.__version__, 'numpyro', numpyro.__version__)"
