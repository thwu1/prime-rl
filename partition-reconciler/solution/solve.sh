#!/bin/bash

pip3 install pytest==8.3.4 pyyaml==6.0.2 -q

cd /app

# Step 1: Fix all Python code and config bugs
python3 /solution/apply_fixes.py

# Step 2: Create SQLite analytical views
sqlite3 /app/warehouse.db < /solution/create_views.sql
echo "Created SQLite analytical views"

# Step 3: Event log audit with jq
jq -s '{
  total_events: length,
  events_by_level: (group_by(.level) | map({key: .[0].level, value: length}) | from_entries),
  staleness_checks: [.[] | select(.event == "STALENESS_CHECK") | {asset, partition, upstream_resolved, result}],
  reported_total_stale: ([.[] | select(.event == "RECONCILIATION_COMPLETE")][0].total_stale),
  reported_total_unmaterialized: ([.[] | select(.event == "RECONCILIATION_COMPLETE")][0].total_unmaterialized)
}' /app/events.jsonl > /app/event_audit.json
echo "Generated event_audit.json"

# Step 4: Run the cost-aware reconciliation planner
PYTHONPATH=/app python3 /solution/run_planner.py

# Verify
PYTHONPATH=/app pytest /tests/test_state.py -v
