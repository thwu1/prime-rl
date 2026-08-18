#!/bin/bash
#SBATCH --job-name=deepswe-relay-cleanup
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_eval/relay_cleanup_%j.log

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl
export MODAL_DISABLE_API_PROXY=1
uv run --no-sync python user/tianhaowu/deepswe_modal/cleanup_relays.py "$@"
