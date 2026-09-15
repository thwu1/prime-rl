#!/bin/bash

# Remove nodes not reachable from any snapshot using recursive CTE.
# Usage: compact.sh <db_path>

DB="${1:-/app/store.db}"

BEFORE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM nodes")

sqlite3 "$DB" "
WITH RECURSIVE reachable(node_id) AS (
    SELECT root_node_id FROM snapshots WHERE root_node_id IS NOT NULL
    UNION
    SELECT CAST(j.value AS INTEGER)
    FROM reachable r
    JOIN nodes n ON n.node_id = r.node_id AND n.is_leaf = 0
    JOIN json_each(n.data) j
)
DELETE FROM nodes WHERE node_id NOT IN (SELECT node_id FROM reachable);
"

AFTER=$(sqlite3 "$DB" "SELECT COUNT(*) FROM nodes")
REMOVED=$((BEFORE - AFTER))
echo "Compacted: removed $REMOVED orphaned nodes ($BEFORE -> $AFTER)"
