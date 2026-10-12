#!/bin/bash
# Submit a Nemotron SFT run on g3 from a frozen snapshot of the current commit.
#
# The venv installs prime-rl editable from the dev checkout, so a job that imports modules while
# the checkout is being edited can crash (this happened). This script checks out HEAD into a
# read-only worktree and puts its src/ first on PYTHONPATH for every rank.
#
# Usage: sft/launch_sft.sh <config.toml> <run_name> [extra sft CLI overrides...]
#   e.g. sft/launch_sft.sh sft/configs/tb4_23_overfit_262k_cp2_8node.toml tb4-23-262k-r3
set -euo pipefail
CONFIG=${1:?config toml (relative to this folder or absolute)}
NAME=${2:?run name}
shift 2
HERE=$(cd "$(dirname "$0")/.." && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
VENV=${VENV:-/storage/home/tianhaowu/.venvs/prime-nemotron-sft-gb300}
OUTPUT_ROOT=${OUTPUT_ROOT:-/checkpoint/ram/tianhaowu/sft_nemotron_gb300/outputs}
SNAPSHOTS=${SNAPSHOTS:-/storage/home/tianhaowu/prime-nemotron-sft-runs}
[[ "$NAME" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "unsafe run name" >&2; exit 2; }
[[ -z "$(git -C "$REPO" status --porcelain=v1 --untracked-files=no)" ]] || { echo "commit tracked changes first" >&2; exit 2; }

commit=$(git -C "$REPO" rev-parse --short=9 HEAD)
snap="$SNAPSHOTS/$commit"
if [[ ! -d "$snap" ]]; then
    git -C "$REPO" worktree add --detach "$snap" "$commit"
    for dep in renderers pydantic-config verifiers; do
        rmdir "$snap/deps/$dep"
        ln -s "$REPO/deps/$dep" "$snap/deps/$dep"
    done
    chmod -R a-w "$snap/src" "$snap/packages"
fi
config_rel=$(realpath --relative-to="$REPO" "$(cd "$HERE" && realpath -e "$CONFIG")")
pythonpath="$snap/src:$snap/packages/prime-rl-configs/src"

cd "$snap"
PYTHONPATH="$pythonpath" "$VENV/bin/sft" @ "$snap/$config_rel" \
    --output-dir "$OUTPUT_ROOT/$NAME" --wandb.name "$NAME" \
    --slurm.project-dir "$snap" \
    --slurm.template-path "$snap/user/tianhaowu/nemotron_tb4_sandoq/sft/multi_node_sft_g3.sbatch.j2" \
    --slurm.pre-run-command "export SFT_VENV=$VENV PYTHONPATH=$pythonpath" \
    "$@"
echo "snapshot=$snap output=$OUTPUT_ROOT/$NAME"
