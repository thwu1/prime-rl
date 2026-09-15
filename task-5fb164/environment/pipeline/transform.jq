# Deduplicate forecasts: for each (event_id, forecaster_id) pair,
# keep one forecast per group, sorted by timestamp
[group_by([.event_id, .forecaster_id])[] | sort_by(.timestamp) | .[0]]
