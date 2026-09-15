#!/bin/bash

set -e

# Step 1: Run Python to create thermo.db and results.json
python3 /app/thermoengine.py

# Step 2: Generate validation.json using jq and sqlite3 CLI
KEYS=$(jq -r 'keys | sort | @json' /app/results.json)
N_ISOTHERMS=$(jq '[.compressibility | to_entries[] | .value | length] | add' /app/results.json)
N_FUGACITY=$(jq '.fugacity | length' /app/results.json)
N_VIRIAL=$(jq '.second_virial | length' /app/results.json)
DB_ISOTHERM=$(sqlite3 /app/thermo.db "SELECT COUNT(*) FROM nist_isotherms;")
DB_SAT=$(sqlite3 /app/thermo.db "SELECT COUNT(*) FROM saturation_ref;")

jq -n \
  --argjson keys "$KEYS" \
  --argjson n_isotherms "$N_ISOTHERMS" \
  --argjson n_fugacity "$N_FUGACITY" \
  --argjson n_virial "$N_VIRIAL" \
  --argjson db_isotherm_count "$DB_ISOTHERM" \
  --argjson db_saturation_count "$DB_SAT" \
  '{keys_present: $keys, n_isotherms: $n_isotherms, n_fugacity: $n_fugacity, n_virial: $n_virial, db_isotherm_count: $db_isotherm_count, db_saturation_count: $db_saturation_count}' \
  > /app/validation.json

echo "Pipeline complete. Outputs: results.json, thermo.db, validation.json"
