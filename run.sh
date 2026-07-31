#!/usr/bin/env bash
# Pinned entry point for every script in this project.
#
# `conda activate scvul` is deliberately not used: it silently failed to switch
# environments during development and installs landed in an unrelated env.
# The interpreter is addressed by absolute path instead, and user-site packages
# are suppressed so the environment is reproducible from requirements.txt.
set -euo pipefail

PY="${SCVUL_PYTHON:-/home/vortex/miniconda3/envs/scvul/bin/python}"

if [[ ! -x "$PY" ]]; then
    echo "error: interpreter not found at $PY" >&2
    echo "create it with: conda create -y -n scvul python=3.11" >&2
    echo "then: PYTHONNOUSERSITE=1 $PY -m pip install -r requirements.txt" >&2
    exit 1
fi

cd "$(dirname "${BASH_SOURCE[0]}")"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$(pwd)${PYTHONPATH:+:$PYTHONPATH}"

# The environment's bin/ must lead PATH: Slither shells out to `solc` by bare
# name, and solc-select's shim lives there. Without this every Slither run
# fails with FileNotFoundError: 'solc' -- which would be silently recorded as
# an analysis failure and corrupt exactly the outcome this study measures.
export PATH="$(dirname "$PY"):$PATH"

# Keep solc installations inside the project so runs are reproducible and do
# not depend on whatever is in the user's home directory.
export SOLC_SELECT_INSTALL_DIR="${SOLC_SELECT_INSTALL_DIR:-$(pwd)/data/raw/solc}"

exec "$PY" "$@"
