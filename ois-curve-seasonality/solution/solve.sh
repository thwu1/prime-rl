#!/bin/bash

set -e

pip3 install pyyaml==6.0.2 -q

cp /solution/multicurve.py /app/calibrate.py

# Create Makefile with proper tab indentation for recipes
T=$(printf '\t')
cat > /app/Makefile <<MAKEFILE
.PHONY: all calibrate report views

all: calibrate report views

calibrate:
${T}python3 /app/calibrate.py

report:
${T}jq '{num_nodes: (.discount_factors | length), num_forward_dates: (.forward_overnight_rates | length), min_df: ([.discount_factors[]] | min), max_df: ([.discount_factors[]] | max), swap_ids: (.swap_pvs | keys), total_abs_pv01: (.bucketed_pv01 | with_entries(.value = ([.value[]] | map(if . < 0 then -. else . end) | add)))}' /app/output/results.json > /app/output/summary.json

views:
${T}sqlite3 /app/output/curves.db "CREATE VIEW IF NOT EXISTS df_monthly AS SELECT substr(node_date, 1, 7) AS month, MIN(df) AS min_df FROM discount_factors GROUP BY substr(node_date, 1, 7);"
${T}sqlite3 /app/output/curves.db "CREATE VIEW IF NOT EXISTS rate_stats AS SELECT swap_id, SUM(pv01) AS total_pv01, MAX(ABS(pv01)) AS max_abs_bucket FROM bucketed_pv01 GROUP BY swap_id;"
MAKEFILE

cd /app
make all
