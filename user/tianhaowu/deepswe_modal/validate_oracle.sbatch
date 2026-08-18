#!/bin/bash
#SBATCH --job-name=deepswe-oracle-gate
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_eval/oracle_gate_%j.log

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

RESULT=${1:?usage: sbatch validate_oracle.sbatch RESULT_JSON}
uv run --no-sync python user/tianhaowu/deepswe_modal/validate_oracle.py \
    "$RESULT" \
    /checkpoint/ram/tianhaowu/deepswe_eval/deep-swe/tasks
