#!/bin/bash
#SBATCH --job-name=deepswe-oracle-modal
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=48:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_eval/oracle_driver_%j.log

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl
export MODAL_DISABLE_API_PROXY=1

CONFIG=${1:?usage: sbatch run_deepswe_oracle.sbatch CONFIG EVAL_NAME}
EVAL_NAME=${2:?usage: sbatch run_deepswe_oracle.sbatch CONFIG EVAL_NAME}
EVAL_JOB_NAME="${EVAL_NAME}-${SLURM_JOB_ID}"

uv run --no-sync python user/tianhaowu/deepswe_modal/pier_runner.py \
    "$CONFIG" \
    "$EVAL_JOB_NAME"

uv run --no-sync python user/tianhaowu/deepswe_modal/validate_oracle.py \
    "/checkpoint/ram/tianhaowu/deepswe_eval/jobs/${EVAL_JOB_NAME}/result.json" \
    /checkpoint/ram/tianhaowu/deepswe_eval/deep-swe/tasks
