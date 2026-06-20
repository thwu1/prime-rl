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
export WANDB_MODE=online
CFG=${CFG:-user/tianhaowu/configs/tb_rl_12k.toml}
OUTDIR=${OUTDIR:-/checkpoint/ram/tianhaowu/tb_rl_12k}
mkdir -p "$OUTDIR"
echo "=== submitting RL training: CFG=$CFG -> $OUTDIR ==="
# --trainer.model.cp-style MUST be on the CLI: RLConfig's validator drops the
# config cp_style, and the default `ring` CP is incompatible with Qwen3.5 hybrid/SSM
# layers. NCCL_RAS_ENABLE=0 + VLLM_DISABLE_COMPILE_CACHE=1 live in the sbatch template.
uv run --no-sync rl @ "$CFG" --output-dir "$OUTDIR" --trainer.model.cp-style ulysses
