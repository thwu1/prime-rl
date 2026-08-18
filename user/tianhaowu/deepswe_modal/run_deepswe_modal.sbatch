#!/bin/bash
#SBATCH --job-name=deepswe-nemotron-modal
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=72:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_eval/driver_%j.log

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

CONFIG=${1:?usage: sbatch run_deepswe_modal.sbatch CONFIG INFERENCE_JOB_ID EVAL_NAME}
INFERENCE_JOB_ID=${2:?usage: sbatch run_deepswe_modal.sbatch CONFIG INFERENCE_JOB_ID EVAL_NAME}
EVAL_NAME=${3:?usage: sbatch run_deepswe_modal.sbatch CONFIG INFERENCE_JOB_ID EVAL_NAME}

uv run --no-sync python user/tianhaowu/deepswe_modal/run_deepswe_modal.py \
    "$CONFIG" \
    --inference-job-id "$INFERENCE_JOB_ID" \
    --job-name "${EVAL_NAME}-${SLURM_JOB_ID}"
