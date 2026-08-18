#!/bin/bash
#SBATCH --job-name=deepswe-modal
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=72:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_eval/driver_%j.log

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

CONFIG=${1:?usage: sbatch submit_eval.sbatch EVAL_CONFIG.toml}
shift

uv run --no-sync python user/tianhaowu/deepswe_modal/submit_eval.py "$CONFIG" "$@"
