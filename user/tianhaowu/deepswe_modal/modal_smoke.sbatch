#!/bin/bash
#SBATCH --job-name=modal-sandbox-smoke
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:10:00
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_eval/modal_smoke_%j.log

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl
export MODAL_DISABLE_API_PROXY=1
uv run --no-sync python user/tianhaowu/deepswe_modal/modal_smoke.py
