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
# vmvm-tb / vmvm-tb-v1 are editable installs that the sbatch's `uv sync` prunes;
# PYTHONPATH (exported -> inherited by the rl job + its orchestrator) keeps both
# importable so a config can pick either env id (vmvm-tb or vmvm-tb-v1).
export PYTHONPATH="$HOME/prime-rl/environments/vmvm_tb:$HOME/prime-rl/environments/vmvm_tb_v1${PYTHONPATH:+:$PYTHONPATH}"
export WANDB_MODE=online
# fla gated-delta (Qwen3.5/3.6) needs tilelang kernels on Hopper: fla's triton path is
# disabled for Triton>=3.4 on H200 (bug #640), and tilelang JITs FP8 UE8M0 CUDA needing
# nvcc>=12.8. Cluster max is /public/apps/cuda/12.6.1, so point CUDA_HOME at a micromamba
# CUDA 12.9 toolkit (matches torch cu129) that has the e8m0 headers. No-op for non-fla models.
export CUDA_HOME=/checkpoint/ram-h100-2/tianhaowu/envs/cuda129
export PATH="$CUDA_HOME/bin:$PATH"
# The rl entrypoint pre-downloads the model on the LOGIN node, whose proxy blocks HF
# (403 Domain not in allowlist). Models are pre-cached under $HF_HOME, so resolve offline.
# (The sbatch template already sets HF_HUB_OFFLINE=1 for the compute-node job.)
export HF_HUB_OFFLINE=1

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
