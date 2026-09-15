#!/usr/bin/env bash
# Station data extraction pipeline
# Extracts and filters gauge measurements for hydrological analysis
set -euo pipefail

STATION_ID="${1:?Usage: extract.sh <station_id>}"
DATA_DIR="/app/data"
CONFIG="$DATA_DIR/stations.json"

# Extract station configuration from nested JSON structure
STATION_CONFIG=$(jq -c ".stations[] | select(.id == \"$STATION_ID\")" "$CONFIG")

if [ -z "$STATION_CONFIG" ]; then
    echo "ERROR: Station '$STATION_ID' not found in config" >&2
    exit 1
fi

DATA_FILE=$(echo "$STATION_CONFIG" | jq -r '.data.source_file')
FLOW_COL=$(echo "$STATION_CONFIG" | jq -r '.data.flow_column_index')
QUALITY_FILTER=$(echo "$STATION_CONFIG" | jq -r '.analysis.quality_filter')

CSV_PATH="$DATA_DIR/$DATA_FILE"

if [ ! -f "$CSV_PATH" ]; then
    echo "ERROR: Data file '$CSV_PATH' not found" >&2
    exit 1
fi

# Extract flow measurements, skip header, filter by quality flag
awk -F',' -v col="$FLOW_COL" -v qf="$QUALITY_FILTER" \
    'NR > 1 && $5 == qf { printf "%.6f\n", $4 }' "$CSV_PATH"
