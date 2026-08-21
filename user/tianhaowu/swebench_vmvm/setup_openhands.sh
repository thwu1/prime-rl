#!/bin/bash

set -euo pipefail

: "${SETUP_ROOT:?Set SETUP_ROOT}"

readonly openhands_repo=https://github.com/sdevare-nv/nv-OpenHands.git
readonly openhands_commit=5f0180054732945df08ad2293903e6873f0492b6
readonly miniforge_dir="$SETUP_ROOT/miniforge3"
readonly openhands_dir="$SETUP_ROOT/OpenHands"
readonly archive="$SETUP_ROOT/openhands-v0.62.0-5f01800.tar.zst"

mkdir -p "$SETUP_ROOT"

if [ ! -x "$miniforge_dir/bin/conda" ] || [ ! -x "$miniforge_dir/bin/mamba" ]; then
    installer="$SETUP_ROOT/Miniforge3-$(uname)-$(uname -m).sh"
    curl --fail --location --output "$installer" \
        "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
    bash "$installer" -b -p "$miniforge_dir"
    rm "$installer"
fi

export PATH="$miniforge_dir/bin:$PATH"
source "$miniforge_dir/etc/profile.d/conda.sh"
conda activate base
mamba install -y --override-channels \
    conda-forge::python=3.12 \
    conda-forge::nodejs \
    conda-forge::poetry=2.1.2 \
    conda-forge::tmux \
    conda-forge::git
if [ ! -x "$miniforge_dir/bin/jq" ]; then
    curl --fail --silent --show-error --location \
        https://github.com/jqlang/jq/releases/download/jq-1.8.1/jq-linux-amd64 \
        --output "$miniforge_dir/bin/jq"
    chmod +x "$miniforge_dir/bin/jq"
fi

if [ ! -d "$openhands_dir/.git" ]; then
    git clone "$openhands_repo" "$openhands_dir"
fi
git -C "$openhands_dir" fetch origin "$openhands_commit"
git -C "$openhands_dir" checkout --force "$openhands_commit"

cd "$openhands_dir"
export INSTALL_DOCKER=0
export POETRY_VIRTUALENVS_IN_PROJECT=true
unset VIRTUAL_ENV PYTHONHOME

poetry env use python3.12
poetry install --no-interaction --no-root
test -x .venv/bin/python
.venv/bin/python -m pip install datasets huggingface_hub

mkdir -p evaluation/oh logs .eval_sessions

cd "$SETUP_ROOT"
rm -rf miniforge3/pkgs miniforge3/conda-meta/history
find OpenHands -type d -name __pycache__ -prune -exec rm -rf {} +

tar --zstd -cf "$archive.tmp" \
    --exclude='OpenHands/frontend/node_modules' \
    --exclude='OpenHands/.venv/.cache' \
    --exclude='OpenHands/.cache' \
    miniforge3 OpenHands
mv "$archive.tmp" "$archive"
sha256sum "$archive" > "$archive.sha256"
du -h "$archive" "$SETUP_ROOT"
