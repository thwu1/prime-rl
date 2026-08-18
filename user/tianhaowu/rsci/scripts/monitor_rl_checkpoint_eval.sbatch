#!/usr/bin/env bash
#SBATCH --job-name=rsci-frozen-monitor
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=7-00:00:00
#SBATCH --requeue

set -euo pipefail

RUN_DIR=${1:?usage: monitor_rl_checkpoint_eval.sbatch RUN_DIR ARRAY_JOB_ID}
ARRAY_JOB_ID=${2:?usage: monitor_rl_checkpoint_eval.sbatch RUN_DIR ARRAY_JOB_ID}
INTERVAL_SECONDS=${RSCI_FROZEN_EVAL_MONITOR_INTERVAL_SECONDS:-60}
STATUS_DIR="$RUN_DIR/evals/op11-45/array"

mkdir -p "$STATUS_DIR"
exec {LOCK_FD}>"$STATUS_DIR/monitor.lock"
if ! flock -n "$LOCK_FD"; then
  echo "another frozen-evaluation monitor already holds $STATUS_DIR/monitor.lock"
  exit 0
fi

SOURCE_BOOTSTRAP="$RUN_DIR/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot.sh"
if [[ ! -f "$SOURCE_BOOTSTRAP" ]]; then
  echo "frozen source bootstrap does not exist: $SOURCE_BOOTSTRAP" >&2
  exit 1
fi
source "$SOURCE_BOOTSTRAP" "$RUN_DIR"
REPO_ROOT=$RSCI_SOURCE_SNAPSHOT
cd "$REPO_ROOT"
exec uv run --no-sync user/tianhaowu/rsci/monitor_rl_checkpoint_eval.py \
  "$RUN_DIR" "$ARRAY_JOB_ID" --interval-seconds "$INTERVAL_SECONDS"
