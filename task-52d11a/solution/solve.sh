#!/bin/bash

cd /app

# Step 1: Use sqlite3 to extract geomagnetic index time series to CSV
sqlite3 -header -csv /app/data/geomag_2024.db \
  "SELECT e.utc_timestamp, g.ap_index, g.dst_index, g.ae_index
   FROM epoch_info e
   JOIN geomag_indices g ON e.epoch_id = g.epoch_id
   WHERE g.ap_index IS NOT NULL
     AND g.dst_index IS NOT NULL
     AND g.ae_index IS NOT NULL
   ORDER BY e.utc_timestamp;" > /app/geomag_extracted.csv

echo "Extracted geomag data: $(wc -l < /app/geomag_extracted.csv) rows"

# Step 2: Use jq to extract epoch and mean motion from OMM JSON
jq -r '.[] | [.EPOCH, .MEAN_MOTION] | @csv' /app/data/omm_52140.json > /app/omm_extracted.csv

echo "Extracted OMM data: $(wc -l < /app/omm_extracted.csv) records"

# Step 3: Run Python analysis on extracted data (pure Python, no external deps)
python3 /solution/analyze.py

# Step 4: Insert results into SQLite database
BEST_INDEX=$(jq -r '.best_index' /app/results.json)
BEST_LAG=$(jq -r '.best_lag_hours' /app/results.json)
BEST_R2=$(jq -r '.best_r_squared' /app/results.json)
N_POINTS=$(jq -r '.n_data_points' /app/results.json)

sqlite3 /app/data/geomag_2024.db "CREATE TABLE IF NOT EXISTS correlation_results (best_index TEXT NOT NULL, best_lag_hours INTEGER NOT NULL, best_r_squared REAL NOT NULL, n_data_points INTEGER NOT NULL);"
sqlite3 /app/data/geomag_2024.db "INSERT INTO correlation_results VALUES ('${BEST_INDEX}', ${BEST_LAG}, ${BEST_R2}, ${N_POINTS});"

echo "Results inserted into SQLite database"

# Verify the insert
sqlite3 /app/data/geomag_2024.db "SELECT * FROM correlation_results;"
