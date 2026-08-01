#!/bin/bash
set -euo pipefail

cd /storage/home/tianhaowu/prime-rl
CONFIG=${1:?usage: bash user/tianhaowu/rsci/scripts/run_frontier.sh <frontier-config.toml>}

mapfile -t FIELDS < <(uv run python - "$CONFIG" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    frontier = tomllib.load(handle)["frontier"]
print(frontier["track"])
print(frontier["experiment_root"])
PY
)
TRACK=${FIELDS[0]}
EXPERIMENT_ROOT=${FIELDS[1]}
mkdir -p "$EXPERIMENT_ROOT"
unset SBATCH_OUTPUT SBATCH_ERROR
exec sbatch \
  --job-name="rsci-frontier-$TRACK" \
  --output="$EXPERIMENT_ROOT/watcher-%j.log" \
  user/tianhaowu/rsci/scripts/run_frontier.sbatch "$CONFIG"
