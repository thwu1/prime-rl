#!/bin/bash
# Launch an SFT run from a config TOML. The prime-rl `sft` entrypoint renders the SLURM
# script from [slurm].template_path and submits the multi-node job itself (no separate driver
# needed, unlike RL). Configs live in user/tianhaowu/fair-sc-3/configs/sft/.
#
# Usage: bash run_sft.sh <config.toml> [extra --cli.overrides ...]
#   e.g. bash run_sft.sh user/tianhaowu/fair-sc-3/configs/sft/kimi12k_bs64.toml
set -euo pipefail
cd "$HOME/prime-rl"
CFG=${1:?usage: run_sft.sh <config.toml> [overrides...]}; shift || true
exec uv run --no-sync sft @ "$CFG" "$@"
