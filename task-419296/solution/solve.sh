#!/bin/bash

cd /app

# Query system variables from the diagnostics database using sqlite3
export TIDB_EXEC_CONCURRENCY=$(sqlite3 /app/diagnostics.db \
  "SELECT variable_value FROM tidb_variables WHERE variable_name='tidb_executor_concurrency'")
export TIDB_DISTSQL_SCAN_CONCURRENCY=$(sqlite3 /app/diagnostics.db \
  "SELECT variable_value FROM tidb_variables WHERE variable_name='tidb_distsql_scan_concurrency'")

# Extract cluster state from topology JSON using jq
export GC_TOMBSTONE_CLEANED=$(jq '.gc.last_run.tombstone_keys_cleaned' /app/cluster_topology.json)
export MAX_STORE_SST_COUNT=$(jq '[.stores[].metrics.sst_file_count] | max' /app/cluster_topology.json)

# Run the diagnostic analyzer (discovers plan-ctl to decode .planpb files,
# queries sqlite3 for incident-level data, reads cluster topology)
python3 /solution/analyzer.py
