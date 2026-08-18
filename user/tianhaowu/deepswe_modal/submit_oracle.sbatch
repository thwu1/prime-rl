#!/bin/bash
#SBATCH --job-name=deepswe-oracle
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH --time=48:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_eval/oracle_driver_%j.log

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

PROVIDER=${1:?usage: sbatch submit_oracle.sbatch modal|vmvm|sandoq}
shift

uv run --no-sync python user/tianhaowu/deepswe_modal/submit_oracle.py \
    --provider "$PROVIDER" \
    "$@"
