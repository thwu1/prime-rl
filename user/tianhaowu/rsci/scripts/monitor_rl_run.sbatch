#!/usr/bin/env bash
#SBATCH --job-name=rsci-rl-monitor
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=2-00:00:00
#SBATCH --output=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/monitor_%j.log
#SBATCH --error=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/monitor_%j.log

set -euo pipefail

JOB_ID=${1:?usage: sbatch monitor_rl_run.sbatch JOB_ID OUTPUT_DIR}
OUTPUT_DIR=${2:?usage: sbatch monitor_rl_run.sbatch JOB_ID OUTPUT_DIR}
INTERVAL_SECONDS=${RSCI_MONITOR_INTERVAL_SECONDS:-3600}
POLL_SECONDS=${RSCI_MONITOR_POLL_SECONDS:-60}

cd /storage/home/tianhaowu/prime-rl
exec uv run --no-sync user/tianhaowu/rsci/monitor_rl_run.py \
  --job-id "$JOB_ID" \
  --output-dir "$OUTPUT_DIR" \
  --interval-seconds "$INTERVAL_SECONDS" \
  --poll-seconds "$POLL_SECONDS"
