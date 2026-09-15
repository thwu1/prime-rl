#!/bin/bash

DIR="$1"
DB="/app/validation.db"

# Remove existing DB to start fresh
rm -f "$DB"

# Create database and table
sqlite3 "$DB" "CREATE TABLE results (
    filename TEXT,
    data_block TEXT,
    alert_count INTEGER,
    max_severity TEXT,
    cell_volume REAL,
    formula_weight REAL,
    density REAL,
    alerts_json TEXT
);"

total=0
with_alerts=0
count_a=0
count_b=0
count_c=0

for cif in "$DIR"/*.cif; do
    [ -f "$cif" ] || continue
    total=$((total + 1))

    json=$(python3 /app/cifcheck.py "$cif" 2>/dev/null)

    filename=$(basename "$cif")
    data_block=$(echo "$json" | jq -r '.data_block // ""')
    alert_count=$(echo "$json" | jq '.alerts | length')
    alerts_json=$(echo "$json" | jq -c '.alerts')
    cell_volume=$(echo "$json" | jq '.computed.cell_volume // null')
    formula_weight=$(echo "$json" | jq '.computed.formula_weight // null')
    density=$(echo "$json" | jq '.computed.density // null')

    # Count alerts by severity using jq
    file_a=$(echo "$json" | jq '[.alerts[] | select(.level == "A")] | length')
    file_b=$(echo "$json" | jq '[.alerts[] | select(.level == "B")] | length')
    file_c=$(echo "$json" | jq '[.alerts[] | select(.level == "C")] | length')

    count_a=$((count_a + file_a))
    count_b=$((count_b + file_b))
    count_c=$((count_c + file_c))

    # Determine max severity for this file
    max_severity="NONE"
    if [ "$file_a" -gt 0 ]; then
        max_severity="A"
    elif [ "$file_b" -gt 0 ]; then
        max_severity="B"
    elif [ "$file_c" -gt 0 ]; then
        max_severity="C"
    fi

    if [ "$alert_count" -gt 0 ]; then
        with_alerts=$((with_alerts + 1))
    fi

    # Escape single quotes for SQL insertion
    esc_filename=$(echo "$filename" | sed "s/'/''/g")
    esc_data_block=$(echo "$data_block" | sed "s/'/''/g")
    esc_alerts=$(echo "$alerts_json" | sed "s/'/''/g")

    sqlite3 "$DB" "INSERT INTO results VALUES (
        '$esc_filename',
        '$esc_data_block',
        $alert_count,
        '$max_severity',
        $cell_volume,
        $formula_weight,
        $density,
        '$esc_alerts'
    );"
done

echo "{\"total_files\":$total,\"files_with_alerts\":$with_alerts,\"alert_counts\":{\"A\":$count_a,\"B\":$count_b,\"C\":$count_c}}"
