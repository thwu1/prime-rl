#!/bin/bash

# Export a snapshot as formatted JSON using sqlite3, Python, and jq.
# Usage: export.sh <db_path> <snapshot_name>

DB="${1:-/app/store.db}"
NAME="$2"

if [ -z "$NAME" ]; then
    echo "Usage: export.sh <db_path> <snapshot_name>" >&2
    exit 1
fi

# Check if snapshot exists using sqlite3
COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM snapshots WHERE name = '${NAME//\'/\'\'}'")
if [ "$COUNT" = "0" ]; then
    echo "Snapshot '$NAME' not found" >&2
    exit 1
fi

# Get metadata using sqlite3 JSON mode
META=$(sqlite3 -json "$DB" "SELECT name, vec_size, shift FROM snapshots WHERE name = '${NAME//\'/\'\'}'")

# Get elements using Python (tree traversal requires the data structure logic)
ELEMENTS=$(python3 -c "
import sys, json
sys.path.insert(0, '/app')
from snapstore import SnapStore
store = SnapStore('$DB')
vec = store.load('$NAME')
print(json.dumps(list(vec)))
")

# Count total nodes in DB
NODE_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM nodes")

# Combine metadata + elements with jq
echo "$META" | jq --argjson elements "$ELEMENTS" --argjson node_count "$NODE_COUNT" '
.[0] | {
  name: .name,
  size: .vec_size,
  shift: .shift,
  total_db_nodes: $node_count,
  elements: $elements
}'
