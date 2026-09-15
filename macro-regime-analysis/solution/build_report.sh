#!/bin/bash

DB=/app/results.db

# Extract each section from the results database using sqlite3 JSON output
YCI=$(sqlite3 -json "$DB" "SELECT start_date, end_date, business_days, min_spread FROM yield_curve_inversions ORDER BY start_date")
SAHM=$(sqlite3 -json "$DB" "SELECT start_date, end_date, peak_indicator FROM sahm_rule_episodes ORDER BY start_date")
FFR_MAX=$(sqlite3 -json "$DB" "SELECT date, value FROM real_ffr_extremes WHERE type='max'")
FFR_MIN=$(sqlite3 -json "$DB" "SELECT date, value FROM real_ffr_extremes WHERE type='min'")
FFR_DEC=$(sqlite3 -json "$DB" "SELECT decade, average FROM real_ffr_decades ORDER BY decade")
M2_REG=$(sqlite3 -json "$DB" "SELECT regime, cnt FROM m2_regime_counts")
M2_MAX=$(sqlite3 -json "$DB" "SELECT date, value FROM m2_growth_extremes WHERE type='max'")
M2_MIN=$(sqlite3 -json "$DB" "SELECT date, value FROM m2_growth_extremes WHERE type='min'")
STRESS=$(sqlite3 -json "$DB" "SELECT date, score FROM composite_stress_months ORDER BY date")
STRESS_MAX=$(sqlite3 -json "$DB" "SELECT date, score FROM composite_stress_months ORDER BY score DESC LIMIT 1")
STRESS_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM composite_stress_months")

# Assemble the full JSON report with jq
jq -n \
  --argjson yci "$YCI" \
  --argjson sahm "$SAHM" \
  --argjson ffr_max "$FFR_MAX" \
  --argjson ffr_min "$FFR_MIN" \
  --argjson ffr_dec "$FFR_DEC" \
  --argjson m2_reg "$M2_REG" \
  --argjson m2_max "$M2_MAX" \
  --argjson m2_min "$M2_MIN" \
  --argjson stress "$STRESS" \
  --argjson stress_max "$STRESS_MAX" \
  --arg stress_count "$STRESS_COUNT" \
  '{
    yield_curve_inversions: $yci,
    sahm_rule_episodes: $sahm,
    real_ffr: {
      max: $ffr_max[0],
      min: $ffr_min[0],
      decade_averages: ($ffr_dec | map({(.decade): .average}) | add)
    },
    m2_growth: {
      regime_counts: ($m2_reg | map({(.regime): .cnt}) | add),
      max_growth: $m2_max[0],
      min_growth: $m2_min[0]
    },
    composite_stress: {
      stress_months: $stress,
      max_stress: $stress_max[0],
      count: ($stress_count | tonumber)
    }
  }' > /app/results.json
