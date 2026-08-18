#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=/storage/home/tianhaowu/prime-rl
OUTPUT_DIR=${1:-/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op11-20-balanced-2k}
TRAIN_PER_OP=${RSCI_TRAIN_PER_OP:-200}
shift $(( $# > 0 ? 1 : 0 ))

cd "$REPO_ROOT"
export PYTHONUNBUFFERED=1
uv run --no-sync python user/tianhaowu/rsci/generate.py \
  --output-dir "$OUTPUT_DIR" \
  --ops 11 12 13 14 15 16 17 18 19 20 \
  --train-per-op "$TRAIN_PER_OP" \
  --validation-per-op 0 \
  --test-per-op 0 \
  --context-mixture zoo=1,teacher=1,movie=1 \
  --mode-mixture forward=0.5,reverse=0.5 \
  --seed 20260803 \
  "$@"

uv run --no-sync python user/tianhaowu/rsci/audit_rl_dataset.py \
  --train-data "$OUTPUT_DIR/train.jsonl" \
  --validation-dir /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/datasets--Interplay-LM-Reasoning--composition/snapshots/a09d5c14c02bfa339143fb00a93274d1a84aa31d/val \
  --operations 11 12 13 14 15 16 17 18 19 20 \
  --expected-per-operation "$TRAIN_PER_OP" \
  --output "$OUTPUT_DIR/audit.json"
