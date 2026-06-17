#!/bin/bash
# Launch RL training of Qwen3.5-35B-A3B on tb_v2 (17k) via prime-rl.
# `rl` renders + submits ONE combined SLURM job (trainer + orchestrator +
# inference); the orchestrator leases VMVM sandboxes (vacli) from the job's head
# node and uses the vmvm-tb env for rewards. Fire-and-forget: run from login.
set -uo pipefail
cd "$HOME/prime-rl"
# vmvm-tb is an editable install that the sbatch's `uv sync` prunes; PYTHONPATH
# (exported -> inherited by the rl job + its orchestrator) keeps it importable.
export PYTHONPATH="$HOME/prime-rl/environments/vmvm_tb${PYTHONPATH:+:$PYTHONPATH}"
export WANDB_MODE=offline
OUTDIR=${OUTDIR:-/checkpoint/ram/tianhaowu/tb_rl_run}
mkdir -p "$OUTDIR"
echo "=== submitting RL training -> $OUTDIR ==="
uv run --no-sync rl @ user/tianhaowu/configs/tb_rl.toml --output-dir "$OUTDIR"
