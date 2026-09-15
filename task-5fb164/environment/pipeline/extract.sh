#!/bin/bash
# Stage 1: Extract data from SQLite and apply jq transformations
mkdir -p /tmp/pipeline

# Export events with all columns needed for scoring
sqlite3 -json /app/data/forecasts.db \
  "SELECT event_id, category, outcome FROM events;" \
  > /tmp/pipeline/events.json

# Export market data
sqlite3 -json /app/data/forecasts.db \
  "SELECT event_id, yes_price, no_price FROM markets;" \
  > /tmp/pipeline/markets.json

# Export all forecasts -- no filtering at extraction stage
sqlite3 -json /app/data/forecasts.db \
  "SELECT event_id, forecaster_id, timestamp, probability FROM forecasts;" \
  > /tmp/pipeline/forecasts_raw.json

# Deduplicate and clean forecasts using jq filter
jq -f /app/pipeline/transform.jq /tmp/pipeline/forecasts_raw.json \
  > /tmp/pipeline/forecasts_clean.json

echo "Extracted $(jq length /tmp/pipeline/events.json) events"
echo "Extracted $(jq length /tmp/pipeline/forecasts_raw.json) raw forecasts"
echo "After cleaning: $(jq length /tmp/pipeline/forecasts_clean.json) forecasts"
