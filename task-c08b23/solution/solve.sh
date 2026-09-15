#!/bin/bash

# Extract Beta data from SQLite to CSV format
mkdir -p /tmp/beta_results

# Query the database for valid results, grouped by vulnerability class
for vclass in bufferErrors PPAC resourceManagement informationLeakage numericErrors hardwareSoC injection; do
    sqlite3 -header -csv /app/data/beta_results.db \
        "SELECT cwe_id AS cwe, test_part AS part, result AS score FROM test_scores WHERE vulnerability_class='${vclass}' AND valid=1 ORDER BY cwe_id, test_part;" \
        > "/tmp/beta_results/${vclass}.csv"
done

# Run the corrected scoring engine
python3 /solution/solve_helper.py
