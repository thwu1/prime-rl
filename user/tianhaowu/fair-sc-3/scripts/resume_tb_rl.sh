#!/bin/bash
# Resume an EXISTING prime-rl RL run from a checkpoint step (reproducible).
# Same env + entrypoint as run_tb_rl.sh, but reuses the existing output dir and
# W&B/SLURM name instead of minting a fresh timestamp, and passes --ckpt.resume-step.
#
# Usage: bash resume_tb_rl.sh <config.toml> <existing_output_dir> <resume_step> [extra rl args...]
#   e.g. bash resume_tb_rl.sh configs/tb_rl_12k_100k_lr1e6_rr_v1.toml \
#          /checkpoint/ram/tianhaowu/tb_rl_12k_100k_lr1e6_rr_v1/20260628-154052 175
#
# Notes:
#   - <config.toml> must be the SAME source config the run was launched with.
#   - The rl entrypoint re-renders configs + rl.sbatch into the existing dir, cleans
#     rollouts/broadcasts past <resume_step>, and resubmits. Checkpoints are preserved.
#   - resume_step must match on trainer and orchestrator; --ckpt.resume-step propagates
#     to both (SharedCheckpointConfig). Use -1 for "latest" only if trainer/orch latest agree.
set -uo pipefail
cd "$HOME/prime-rl"
# vmvm-tb / vmvm-tb-v1 are editable installs that `uv sync` prunes; PYTHONPATH (exported ->
# inherited by the rl job + its orchestrator via sbatch --export=ALL) keeps both importable.
export PYTHONPATH="$HOME/prime-rl/environments/vmvm_tb:$HOME/prime-rl/environments/vmvm_tb_v1:$HOME/prime-rl/environments/vmvm_tb_v2${PYTHONPATH:+:$PYTHONPATH}"
export WANDB_MODE=online
# Same CUDA env as run_tb_rl.sh (kept identical so either script works for any model).
# CUDA_HOME points at a COMPLETE micromamba CUDA 12.9 toolkit (nvcc + cudart + cccl + cuBLAS/
# libraries-dev) — matches torch's cu129 build. Required by fla gated-delta models (their
# tilelang backward JITs FP8 UE8M0 CUDA needing nvcc>=12.8; cluster system CUDA is 12.6.1),
# and safe for everything else (it's a full 12.9 dev toolkit; vLLM/FlashInfer build against it).
export CUDA_HOME=/checkpoint/ram-h100-2/tianhaowu/envs/cuda129
export PATH="$CUDA_HOME/bin:$PATH"
# rl pre-downloads the model on the login node (proxy blocks HF); models are pre-cached
# under $HF_HOME so resolve offline. No-op when the config uses a local model path.
export HF_HUB_OFFLINE=1

if [ $# -lt 3 ]; then
  echo "usage: $0 <config.toml> <existing_output_dir> <resume_step> [extra rl args...]" >&2
  exit 2
fi
CFG=$1; OUTDIR=$2; STEP=$3; shift 3
if [ ! -d "$OUTDIR" ]; then echo "error: output dir does not exist: $OUTDIR" >&2; exit 2; fi
STEM=$(basename "$(dirname "$OUTDIR")")
TS=$(basename "$OUTDIR")
RUN_NAME="$STEM-$TS"

echo "=== resuming RL training ==="
echo "  CFG:    $CFG"
echo "  OUTDIR: $OUTDIR  (reused)"
echo "  RESUME: step $STEP"
echo "  WANDB:  $RUN_NAME"
echo "  SLURM:  $RUN_NAME"
uv run --no-sync rl @ "$CFG" \
  --output-dir "$OUTDIR" \
  --wandb.name "$RUN_NAME" \
  --slurm.job-name "$RUN_NAME" \
  --ckpt.resume-step "$STEP" \
  "$@"
