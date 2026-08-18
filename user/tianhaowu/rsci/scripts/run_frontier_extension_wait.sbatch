#!/bin/bash
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=7-00:00:00

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl
CONFIG=${1:?usage: sbatch user/tianhaowu/rsci/scripts/run_frontier_extension_wait.sbatch <frontier-config.toml>}
export HF_HUB_OFFLINE=1
export PYTHONDONTWRITEBYTECODE=1
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

mapfile -t FIELDS < <(uv run --no-sync python - "$CONFIG" <<'PY'
import sys
import tomllib
from pathlib import Path

with Path(sys.argv[1]).open("rb") as handle:
    frontier = tomllib.load(handle)["frontier"]
print(frontier["track"])
print(frontier["experiment_root"])
PY
)
TRACK=${FIELDS[0]}
EXPERIMENT_ROOT=${FIELDS[1]}
WATCHER_NAME="rsci-frontier-$TRACK"

while true; do
  STATUS=$(uv run --no-sync python - "$EXPERIMENT_ROOT/state.json" <<'PY'
import json
import sys
from pathlib import Path

state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(state["status"])
PY
  )

  if [ "$STATUS" = "stopped_at_frontier" ]; then
    echo "frontier already stopped; no extension required"
    exit 0
  fi
  if [ "$STATUS" = "max_operation_exhausted" ]; then
    break
  fi
  if [ "$STATUS" != "running" ]; then
    echo "expected running, max_operation_exhausted, or stopped_at_frontier, found $STATUS" >&2
    exit 1
  fi

  WATCHER_IDS=$(squeue --noheader --name "$WATCHER_NAME" --format=%A)
  if [ -z "$WATCHER_IDS" ]; then
    sleep 60
    WATCHER_IDS=$(squeue --noheader --name "$WATCHER_NAME" --format=%A)
    if [ -z "$WATCHER_IDS" ]; then
      echo "frontier state is running but no $WATCHER_NAME job is active" >&2
      exit 1
    fi
  fi
  sleep 60
done

uv run --no-sync user/tianhaowu/rsci/frontier_extend.py "$CONFIG"
bash user/tianhaowu/rsci/scripts/run_frontier.sh "$CONFIG"
