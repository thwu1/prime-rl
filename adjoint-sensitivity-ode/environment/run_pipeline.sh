#!/bin/bash
# Pipeline orchestration for Lotka-Volterra parameter estimation

set -euo pipefail

echo "=== Lotka-Volterra Parameter Recovery Pipeline ==="

CONFIG="/app/config.toml"
if [ ! -f "$CONFIG" ]; then
    echo "Error: config.toml not found"
    exit 1
fi

RESULTS_DIR=$(python3 -c "
import tomllib
with open('$CONFIG', 'rb') as f:
    config = tomllib.load(f)
print(config['output']['results_dir'])
")

OBS_FILE=$(python3 -c "
import tomllib
with open('$CONFIG', 'rb') as f:
    config = tomllib.load(f)
print(config['data']['observations_file'])
")

META_FILE=$(python3 -c "
import tomllib
with open('$CONFIG', 'rb') as f:
    config = tomllib.load(f)
print(config['data']['metadata_file'])
")

echo "Results directory: $RESULTS_DIR"
echo "Observations:      $OBS_FILE"
echo "Metadata:          $META_FILE"

for f in "$OBS_FILE" "$META_FILE"; do
    if [ ! -f "$f" ]; then
        echo "Error: data file not found: $f"
        exit 1
    fi
done

N_OBS=$(tail -n +2 "$OBS_FILE" | wc -l)
echo "Number of observations: $N_OBS"

mkdir -p "$RESULTS_DIR"

cd /app
python3 driver.py

echo "=== Pipeline Complete ==="
