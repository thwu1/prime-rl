#!/bin/bash

set -e

mkdir -p /app/output

# Step 1: Use jq to extract resource manifest from FHIR Bundles
# Extract resource type counts
jq -s '[.[].entry[].resource.resourceType] | group_by(.) | map({key: .[0], value: length}) | from_entries' \
  /app/bundles/*.json > /tmp/type_counts.json

# Count total resources
TOTAL=$(jq -s '[.[].entry[].resource] | length' /app/bundles/*.json)

# Extract all unique reference targets via recursive descent
jq -s '[.[].entry[].resource | .. | objects | select(has("reference")) | .reference] | unique | sort' \
  /app/bundles/*.json > /tmp/refs.json

# Build manifest object
jq -n \
  --argjson types "$(cat /tmp/type_counts.json)" \
  --argjson total "$TOTAL" \
  --argjson refs "$(cat /tmp/refs.json)" \
  '{total_resources: $total, resource_types: $types, references: $refs}' \
  > /tmp/manifest.json

# Step 2: Run Python evaluator for search queries
python3 /app/evaluator.py --bundles /app/bundles --queries /app/queries.json \
  > /tmp/search_results.json

# Step 3: Run round-trip validation
python3 -c "
import json, sys
sys.path.insert(0, '/app')
from fhir_search import parse_fhir_search, build_query_string

queries = [
    'status=active',
    'code=http://loinc.org|8867-4',
    'date=ge2024-01-01&date=le2024-01-31',
    'name:exact=John',
    '_sort=date,-name&_count=10',
    '_include=Patient:organization',
    '_has:Observation:subject:code=8867-4',
    'status=active,completed&_summary=count',
    'value-quantity=gt80',
    'code-value-quantity=http://loinc.org|8867-4\$gt80',
]

results = []
for q in queries:
    parsed1 = parse_fhir_search(q)
    rebuilt = build_query_string(parsed1)
    parsed2 = parse_fhir_search(rebuilt)
    results.append({
        'query': q,
        'rebuilt': rebuilt,
        'match': parsed1.to_dict() == parsed2.to_dict(),
    })

json.dump(results, sys.stdout, indent=2)
" > /tmp/roundtrip.json

# Step 4: Merge all sections using jq
jq -s '{manifest: .[0], search_results: .[1], round_trip: .[2]}' \
  /tmp/manifest.json /tmp/search_results.json /tmp/roundtrip.json \
  > /app/output/results.json

echo "Pipeline complete. Results at /app/output/results.json"
