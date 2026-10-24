# Source this on Iridis (or any HPC with /scratch/$USER) before running uv:
#   source scripts/hpc_env.sh
# Keeps uv's package cache and Python downloads off the small home quota.
if [ -d "/scratch/$USER" ]; then
    export UV_CACHE_DIR="${UV_CACHE_DIR:-/scratch/$USER/.cache/uv}"
    export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/scratch/$USER/.local/share/uv/python}"
    export UV_LINK_MODE=copy  # cache and project can sit on different filesystems
fi
export PATH="$HOME/.local/bin:$PATH"
