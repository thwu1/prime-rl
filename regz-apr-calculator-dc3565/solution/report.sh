#!/bin/bash
#
# Report generator: queries sqlite3 CLI and assembles summary JSON with jq.

DB="/app/results.db"

TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM loan_results")
REGULAR=$(sqlite3 "$DB" "SELECT COUNT(*) FROM loan_results WHERE transaction_type='regular'")
IRREGULAR=$(sqlite3 "$DB" "SELECT COUNT(*) FROM loan_results WHERE transaction_type='irregular'")
HIGH_COST=$(sqlite3 "$DB" "SELECT COUNT(*) FROM loan_results WHERE high_cost=1")
AVG_SPREAD=$(sqlite3 "$DB" "SELECT ROUND(AVG(rate_spread), 2) FROM loan_results")
FAILURES=$(sqlite3 "$DB" "SELECT json_group_array(id) FROM (SELECT id FROM loan_results WHERE within_tolerance=0 ORDER BY id)")

jq -n \
  --argjson total "$TOTAL" \
  --argjson regular "$REGULAR" \
  --argjson irregular "$IRREGULAR" \
  --argjson high_cost "$HIGH_COST" \
  --argjson avg_spread "$AVG_SPREAD" \
  --argjson failures "$FAILURES" \
  '{total_loans: $total, regular_count: $regular, irregular_count: $irregular, high_cost_count: $high_cost, tolerance_failures: $failures, avg_rate_spread: $avg_spread}'
