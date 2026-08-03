#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=/storage/home/tianhaowu/prime-rl
CONFIG=${1:-user/tianhaowu/rsci/configs/rl/op11_20_strict_grpo_r128.toml}
if (( $# > 0 )); then
  shift
fi

cd "$REPO_ROOT"
unset SBATCH_OUTPUT SBATCH_ERROR
uv run --no-sync rl @ "$CONFIG" "$@"
