#!/bin/bash
# Launch RL training of Qwen3.5-35B-A3B on tb_v2 (17k) via prime-rl.
# `rl` renders + submits ONE combined SLURM job (trainer + orchestrator +
# inference); the orchestrator leases VMVM sandboxes (vacli) from the job's head
# node and uses the vmvm-tb env for rewards. Fire-and-forget: run from login.
#
# Usage: bash run_tb_rl.sh <config.toml> [extra rl args...]
#   Output dir: /checkpoint/ram/tianhaowu/<cfg-stem>/<YYYYMMDD-HHMMSS>/  (PT)
#   W&B name:   <cfg-stem>-<YYYYMMDD-HHMMSS>
set -uo pipefail
cd "$HOME/prime-rl"
# vmvm-tb is an editable install that the sbatch's `uv sync` prunes; PYTHONPATH
# (exported -> inherited by the rl job + its orchestrator) keeps it importable.
export PYTHONPATH="$HOME/prime-rl/environments/vmvm_tb${PYTHONPATH:+:$PYTHONPATH}"
export WANDB_MODE=online

if [ $# -lt 1 ]; then
  echo "usage: $0 <config.toml> [extra rl args...]" >&2
  exit 2
fi
CFG=$1; shift
STEM=$(basename "$CFG" .toml)
TS=$(TZ=America/Los_Angeles date +%Y%m%d-%H%M%S)
OUTDIR="/checkpoint/ram/tianhaowu/$STEM/$TS"
RUN_NAME="$STEM-$TS"
mkdir -p "$OUTDIR"

echo "=== submitting RL training ==="
echo "  CFG:    $CFG"
echo "  OUTDIR: $OUTDIR"
echo "  WANDB:  $RUN_NAME"
echo "  SLURM:  $RUN_NAME"
# NCCL_RAS_ENABLE=0 + VLLM_DISABLE_COMPILE_CACHE=1 live in the sbatch template.
uv run --no-sync rl @ "$CFG" \
  --output-dir "$OUTDIR" \
  --wandb.name "$RUN_NAME" \
  --slurm.job-name "$RUN_NAME" \
  "$@"
