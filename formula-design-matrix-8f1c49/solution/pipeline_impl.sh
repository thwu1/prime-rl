#!/bin/bash

# Multi-tool validation pipeline using sqlite3, jq, and the CLI wrapper.
# Initializes a SQLite database from init.sql, runs each test case through
# the CLI, compares output using jq, and records results in the database.

set -u

DB_PATH="/app/results.db"
INIT_SQL="/app/init.sql"

# Step 1: Initialize database from init.sql
rm -f "$DB_PATH"
sqlite3 "$DB_PATH" < "$INIT_SQL"

# Step 2: Get all test case IDs
tc_ids=$(sqlite3 "$DB_PATH" "SELECT id FROM test_cases ORDER BY id;")

total=0
passed=0

for tc_id in $tc_ids; do
    total=$((total + 1))

    # Extract test case data from SQLite
    tc_name=$(sqlite3 "$DB_PATH" "SELECT name FROM test_cases WHERE id=$tc_id;")
    formula=$(sqlite3 "$DB_PATH" "SELECT formula FROM test_cases WHERE id=$tc_id;")
    data_json=$(sqlite3 "$DB_PATH" "SELECT data_json FROM test_cases WHERE id=$tc_id;")
    expected_cols=$(sqlite3 "$DB_PATH" "SELECT columns_json FROM expected_outputs WHERE test_case_id=$tc_id;")
    expected_mat=$(sqlite3 "$DB_PATH" "SELECT matrix_json FROM expected_outputs WHERE test_case_id=$tc_id;")

    # Convert data_json to CSV using jq
    csv_input=$(echo "$data_json" | jq -r '
        . as $d |
        (keys_unsorted) as $ks |
        ($ks | join(",")),
        (($d[$ks[0]] | length) as $n |
         range($n) | . as $i |
         [$ks[] as $k | $d[$k][$i] | tostring] | join(","))
    ')

    # Run CLI with --json flag and capture output
    if ! cli_output=$(echo "$csv_input" | python3 /app/cli.py "$formula" --json 2>/dev/null); then
        esc_name=$(echo "$tc_name" | sed "s/'/''/g")
        sqlite3 "$DB_PATH" "INSERT INTO pipeline_results (test_case_id, status, error_message) VALUES ($tc_id, 'error', 'CLI execution failed for $esc_name');"
        echo "ERROR $tc_name: CLI execution failed"
        continue
    fi

    # Extract columns and matrix from CLI JSON output using jq
    actual_cols=$(echo "$cli_output" | jq -c '.columns')
    actual_mat=$(echo "$cli_output" | jq -c '.matrix')

    # Compare columns using jq (exact structural match)
    cols_match=$(jq -n --argjson actual "$actual_cols" --argjson expected "$expected_cols" \
        'if $actual == $expected then "yes" else "no" end' -r)

    # Compare matrix values with floating-point tolerance using jq + python
    mat_match=$(jq -n --argjson actual "$actual_mat" --argjson expected "$expected_mat" \
        '{actual: $actual, expected: $expected}' | python3 -c "
import json, sys
d = json.load(sys.stdin)
a, e = d['actual'], d['expected']
ok = (len(a) == len(e) and
      all(len(ar) == len(er) for ar, er in zip(a, e)) and
      all(abs(float(av) - float(ev)) < 1e-6
          for ar, er in zip(a, e)
          for av, ev in zip(ar, er)))
print('yes' if ok else 'no')
" 2>/dev/null) || mat_match="no"

    # Escape JSON values for SQL insertion (double single quotes)
    esc_cols=$(echo "$actual_cols" | sed "s/'/''/g")
    esc_mat=$(echo "$actual_mat" | sed "s/'/''/g")

    if [ "$cols_match" = "yes" ] && [ "$mat_match" = "yes" ]; then
        sqlite3 "$DB_PATH" "INSERT INTO pipeline_results (test_case_id, columns_json, matrix_json, status) VALUES ($tc_id, '$esc_cols', '$esc_mat', 'pass');"
        echo "  ok $tc_name"
        passed=$((passed + 1))
    else
        msg=""
        [ "$cols_match" != "yes" ] && msg="columns mismatch"
        [ "$mat_match" != "yes" ] && msg="${msg:+$msg; }matrix mismatch"
        esc_msg=$(echo "$msg" | sed "s/'/''/g")
        sqlite3 "$DB_PATH" "INSERT INTO pipeline_results (test_case_id, columns_json, matrix_json, status, error_message) VALUES ($tc_id, '$esc_cols', '$esc_mat', 'fail', '$esc_msg');"
        echo "FAIL $tc_name: $msg"
    fi
done

echo ""
echo "$passed/$total pipeline cases passed"

[ "$passed" -eq "$total" ]
