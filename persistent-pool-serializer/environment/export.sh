#!/bin/bash
# Export a snapshot as formatted JSON to stdout.
# Usage: export.sh <db_path> <snapshot_name>
#
# Output format:
# {
#   "name": "<snapshot_name>",
#   "size": <element_count>,
#   "shift": <tree_depth>,
#   "total_db_nodes": <node_count_in_db>,
#   "elements": [<values...>]
# }
#
# Must use sqlite3 and jq in the pipeline.
echo "ERROR: export not implemented" >&2
exit 1
