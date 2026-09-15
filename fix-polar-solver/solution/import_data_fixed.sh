#!/bin/bash
# Import evaluation results into SQLite database
# Uses sqlite3 CLI with staging tables for CSV import

DB="/app/benchmark.db"
rm -f "$DB"

# Create schema
sqlite3 "$DB" < /app/benchmark_schema.sql

# Insert configurations from extracted JSON files
for f in /app/build/extracted/*.json; do
    NAME=$(jq -r '.name' "$f")
    NUM_ITER=$(jq '.coefficients | length' "$f")
    COEFFS=$(jq -c '.coefficients' "$f")
    sqlite3 "$DB" "INSERT INTO configurations (name, num_iterations, coefficients) VALUES ('$NAME', $NUM_ITER, '$COEFFS');"
done

# Insert matrices from specs
jq -c '.matrices[]' /app/matrix_specs.json | while read -r row; do
    NAME=$(echo "$row" | jq -r '.name')
    CAT=$(echo "$row" | jq -r '.category')
    ROWS=$(echo "$row" | jq -r '.rows')
    COLS=$(echo "$row" | jq -r '.cols')
    SEED=$(echo "$row" | jq -r '.seed')
    sqlite3 "$DB" "INSERT INTO matrices (name, category, rows, cols, seed) VALUES ('$NAME', '$CAT', $ROWS, $COLS, $SEED);"
done

# Import benchmark results via staging table
sqlite3 "$DB" <<'SQLEOF'
.mode csv
CREATE TEMP TABLE bench_staging(config_name TEXT, matrix_name TEXT, orthogonality_error REAL, gram_matches_standard INTEGER);
.import --skip 1 /app/build/benchmark_results.csv bench_staging
INSERT INTO benchmark_results (config_id, matrix_id, orthogonality_error, gram_matches_standard)
SELECT c.id, m.id, s.orthogonality_error, s.gram_matches_standard
FROM bench_staging s
JOIN configurations c ON c.name = s.config_name
JOIN matrices m ON m.name = s.matrix_name;
SQLEOF

# Import stability results via staging table
sqlite3 "$DB" <<'SQLEOF'
.mode csv
CREATE TEMP TABLE stab_staging(config_name TEXT, num_restarts INTEGER, optimal_positions TEXT, stability_metric REAL);
.import --skip 1 /app/build/stability_results.csv stab_staging
INSERT INTO stability_results (config_id, num_restarts, optimal_positions, stability_metric)
SELECT c.id, s.num_restarts, s.optimal_positions, s.stability_metric
FROM stab_staging s
JOIN configurations c ON c.name = s.config_name;
SQLEOF

echo "Database import complete."
