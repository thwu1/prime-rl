#!/bin/bash

DB=/app/results.db
OUT=/app/report.json

te=$(sqlite3 "$DB" "SELECT COUNT(DISTINCT entity_id) FROM entity_results")
tey=$(sqlite3 "$DB" "SELECT COUNT(*) FROM entity_results")
ad=$(sqlite3 "$DB" "SELECT ROUND(SUM(deductible_bie),2) FROM entity_results")
adi=$(sqlite3 "$DB" "SELECT ROUND(SUM(disallowed_bie),2) FROM entity_results")
rl=$(sqlite3 "$DB" "SELECT COUNT(*) FROM loan_recharacterizations WHERE recharacterized=1")
tir=$(sqlite3 "$DB" "SELECT ROUND(SUM(annual_interest_removed),2) FROM loan_recharacterizations")
mcf_entity=$(sqlite3 "$DB" "SELECT entity_id FROM entity_results ORDER BY carryforward_bie DESC LIMIT 1")
mcf_amount=$(sqlite3 "$DB" "SELECT ROUND(MAX(carryforward_bie),2) FROM entity_results")
efr=$(sqlite3 "$DB" "SELECT COUNT(*) FROM ebie_balances WHERE ROUND(balance,2)=0.0")

jq -n \
  --argjson te "$te" \
  --argjson tey "$tey" \
  --argjson ad "$ad" \
  --argjson adi "$adi" \
  --argjson rl "$rl" \
  --argjson tir "$tir" \
  --arg mce "$mcf_entity" \
  --argjson mca "$mcf_amount" \
  --argjson efr "$efr" \
  '{
    total_entities: $te,
    total_entity_years: $tey,
    aggregate_deductible: $ad,
    aggregate_disallowed: $adi,
    recharacterized_loans: $rl,
    total_interest_removed: $tir,
    max_carryforward_entity: $mce,
    max_carryforward_amount: $mca,
    ebie_fully_resolved: $efr
  }' > "$OUT"
