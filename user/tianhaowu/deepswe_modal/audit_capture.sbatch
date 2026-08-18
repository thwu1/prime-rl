#!/bin/bash
#SBATCH --job-name=deepswe-audit
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_eval/audit_%j.log

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

DRIVER_DIR=${1:?usage: sbatch audit_capture.sbatch DRIVER_DIR INFERENCE_JOB_ID}
INFERENCE_JOB_ID=${2:?usage: sbatch audit_capture.sbatch DRIVER_DIR INFERENCE_JOB_ID}

uv run --no-sync python user/tianhaowu/deepswe_modal/audit_capture.py \
  "$DRIVER_DIR" \
  --inference-job-id "$INFERENCE_JOB_ID"
