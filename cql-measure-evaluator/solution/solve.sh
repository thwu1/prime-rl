#!/bin/bash

# Step 1: Use jq to extract measure population criteria from FHIR Measure resource
echo "=== Extracting population criteria from FHIR Measure ==="
jq -r '.group[0].population[] | "\(.code.coding[0].code): \(.criteria.expression)"' /app/measure/CMS165v14.json

# Step 2: Verify terminology database schema and content via sqlite3
echo "=== Terminology database summary ==="
sqlite3 /app/terminology.db "SELECT vs.title, COUNT(c.id) as code_count FROM value_sets vs JOIN codes c ON c.value_set_id = vs.id GROUP BY vs.id ORDER BY vs.title;"

# Step 3: Use jq to verify patient bundle structure
echo "=== Patient bundle resource type summary ==="
for f in /app/patients/*.json; do
    patient_id=$(basename "$f" .json)
    resource_types=$(jq -r '[.entry[].resource.resourceType] | group_by(.) | map("\(.[0]):\(length)") | join(", ")' "$f")
    echo "  $patient_id: $resource_types"
done

# Step 4: Run the evaluator (uses sqlite3 + jq + Python)
echo "=== Running CQL evaluation pipeline ==="
cp /solution/evaluator.py /app/evaluate.py
cd /app
python3 evaluate.py
