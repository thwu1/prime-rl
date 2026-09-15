#!/usr/bin/env bash

# Diagnostic report: query telemetry SQLite DB and format with jq

DB="/app/telemetry.db"

if [ ! -f "$DB" ]; then
    echo '{"error": "telemetry database not found"}' | jq '.'
    exit 1
fi

TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM connection_events;")

EVENTS=$(sqlite3 "$DB" \
  "SELECT json_group_array(json_object('event_type', event_type, 'count', cnt)) \
   FROM (SELECT event_type, COUNT(*) as cnt FROM connection_events GROUP BY event_type);")

printf '{"total_events": %d, "events_by_type": %s}\n' "$TOTAL" "$EVENTS" | jq '.'
