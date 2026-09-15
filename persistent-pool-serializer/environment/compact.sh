#!/bin/bash
# Remove nodes from the database that are not reachable from any snapshot.
# Usage: compact.sh <db_path>
#
# Must use the sqlite3 CLI to identify and delete orphaned nodes.
# A node is orphaned if it is not referenced (directly or transitively)
# by any snapshot's root node.
echo "ERROR: compact not implemented" >&2
exit 1
