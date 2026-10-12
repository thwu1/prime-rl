#!/bin/bash
# Turn a content-part SFT export (e.g. ThWu/tmp nemotron-tb4-23-overfit-174-20260926/traces.sft.jsonl)
# into the string + reasoning_content shape the nemotron-3 renderer reads, then verify the render.
# Usage: data/prepare.sh <traces.sft.jsonl> <out_dir>
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${1:?traces.sft.jsonl}
OUT=${2:?output dir}
VENV=${VENV:-/storage/home/tianhaowu/.venvs/prime-nemotron-sft-gb300}
TOKENIZER=${TOKENIZER:-/checkpoint/ram/tianhaowu/models/NVIDIA-Nemotron-3-Super-120B-A12B-BF16}

"$VENV/bin/python" "$HERE/convert_parts.py" --src "$SRC" --dst "$OUT/train/train.jsonl"
# Every assistant thinking/text/tool-call must land in the trained span; nothing else may.
HF_HUB_OFFLINE=1 "$VENV/bin/python" "$HERE/check_render.py" --data "$OUT/train/train.jsonl" \
    --tokenizer "$TOKENIZER" --seq-len "${SEQ_LEN:-262144}" --dump 0
