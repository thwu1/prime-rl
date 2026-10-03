#!/bin/bash
#SBATCH --job-name=nemotron-dcp-to-hf
#SBATCH --partition=g3
#SBATCH --qos=g3_ram_high
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:4
#SBATCH --mem=0
#SBATCH --time=04:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/sft_nemotron_gb300/logs/convert_%j.log
# Convert a final DCP trainer checkpoint to an HF safetensors dir (for runs saved with
# skip_gather_master_weights = true). Streams one layer at a time; no GPU needed, but only g3 is
# aarch64 so it runs there.
# Usage: sbatch sft/convert_checkpoint.sh <run_output_dir> <step> [base_model_dir]
set -euo pipefail
RUN=${1:?run output dir}
STEP=${2:?step}
BASE=${3:-/checkpoint/ram/tianhaowu/models/NVIDIA-Nemotron-3-Super-120B-A12B-BF16}
VENV=${VENV:-/storage/home/tianhaowu/.venvs/prime-nemotron-sft-gb300}
HERE=${NEMOTRON_TB4_SANDOQ_DIR:-/storage/home/tianhaowu/prime-nemotron-sft-512k/user/tianhaowu/nemotron_tb4_sandoq}
DCP="$RUN/checkpoints/step_$STEP/trainer"
OUT="$RUN/weights/step_$STEP"
[[ -f "$DCP/.metadata" ]] || { echo "no DCP checkpoint at $DCP" >&2; exit 2; }
CUDA_VISIBLE_DEVICES= HF_HUB_OFFLINE=1 "$VENV/bin/python" "$HERE/sft/convert_dcp_to_hf.py" \
    --dcp-dir "$DCP" --base-model "$BASE" --output-dir "$OUT"
echo "converted: $OUT"
