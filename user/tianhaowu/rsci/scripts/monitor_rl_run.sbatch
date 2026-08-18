#!/usr/bin/env bash
#SBATCH --job-name=rsci-rl-monitor
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=4-00:00:00
#SBATCH --output=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/monitor_%j.log
#SBATCH --error=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/monitor_%j.log

set -euo pipefail

JOB_ID=${1:?usage: sbatch monitor_rl_run.sbatch JOB_ID OUTPUT_DIR [MAX_STEPS]}
OUTPUT_DIR=${2:?usage: sbatch monitor_rl_run.sbatch JOB_ID OUTPUT_DIR [MAX_STEPS]}
MAX_STEPS=${3:-500}
INTERVAL_SECONDS=${RSCI_MONITOR_INTERVAL_SECONDS:-3600}
POLL_SECONDS=${RSCI_MONITOR_POLL_SECONDS:-60}
STATUS_PATH="$OUTPUT_DIR/STATUS.md"

for ((attempt = 0; attempt < 60; attempt++)); do
  [[ -f "$STATUS_PATH" ]] && break
  sleep 5
done
if [[ ! -f "$STATUS_PATH" ]]; then
  echo "Run status file did not appear within 300 seconds: $STATUS_PATH" >&2
  exit 1
fi

cd /storage/home/tianhaowu/prime-rl
exec uv run --no-sync user/tianhaowu/rsci/monitor_rl_run.py \
  --job-id "$JOB_ID" \
  --output-dir "$OUTPUT_DIR" \
  --max-steps "$MAX_STEPS" \
  --interval-seconds "$INTERVAL_SECONDS" \
  --poll-seconds "$POLL_SECONDS"
