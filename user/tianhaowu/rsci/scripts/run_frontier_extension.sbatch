#!/bin/bash
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl
CONFIG=${1:?usage: sbatch user/tianhaowu/rsci/scripts/run_frontier_extension.sbatch <frontier-config.toml>}
export HF_HUB_OFFLINE=1
export PYTHONDONTWRITEBYTECODE=1
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

STATUS=$(uv run --no-sync python - "$CONFIG" <<'PY'
import json
import sys
import tomllib
from pathlib import Path

with Path(sys.argv[1]).open("rb") as handle:
    frontier = tomllib.load(handle)["frontier"]
state = json.loads((Path(frontier["experiment_root"]) / "state.json").read_text(encoding="utf-8"))
print(state["status"])
PY
)

if [ "$STATUS" = "stopped_at_frontier" ]; then
  echo "frontier already stopped; no extension required"
  exit 0
fi
if [ "$STATUS" != "max_operation_exhausted" ]; then
  echo "expected max_operation_exhausted or stopped_at_frontier, found $STATUS" >&2
  exit 1
fi

uv run --no-sync user/tianhaowu/rsci/frontier_extend.py "$CONFIG"
bash user/tianhaowu/rsci/scripts/run_frontier.sh "$CONFIG"
