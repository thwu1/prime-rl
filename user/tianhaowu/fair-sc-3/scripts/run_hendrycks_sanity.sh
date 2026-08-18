#!/bin/bash
# Launch Hendrycks Sanity Check RL training (single-node 8 GPU).
# Usage: bash run_hendrycks_sanity.sh [config.toml] [extra rl args...]
#   Output dir: /checkpoint/ram/tianhaowu/<cfg-stem>/<YYYYMMDD-HHMMSS>/
#   W&B name:   <cfg-stem>-<YYYYMMDD-HHMMSS>
set -uo pipefail
cd "$HOME/prime-rl"

# Unset proxy: login node needs HF access for model download,
# compute nodes need direct intra-cluster communication.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

export WANDB_MODE=online

CFG="${1:-user/tianhaowu/fair-sc-3/configs/hendrycks_sanity.toml}"
shift 2>/dev/null || true
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
uv run --no-sync rl @ "$CFG" \
  --output-dir "$OUTDIR" \
  --wandb.name "$RUN_NAME" \
  --slurm.job-name "$RUN_NAME" \
  "$@"
