#!/bin/bash
set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

CONFIG=${1:?usage: bash user/tianhaowu/rsci/scripts/run_sft.sh <sft-config.toml> [overrides]}
shift

export HF_HUB_OFFLINE=1
unset SBATCH_OUTPUT SBATCH_ERROR
exec uv run sft @ "$CONFIG" "$@"
