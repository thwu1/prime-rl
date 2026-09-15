#!/bin/bash

set -e

pip3 install pyyaml==6.0.2 jsonschema==4.23.0 -q

cp /solution/auditor_solution.py /app/auditor.py
cd /app
python3 /app/auditor.py

# Generate unified diffs for each device
mkdir -p /app/diffs
for cfg in /app/configs/*.cfg; do
    name=$(basename "$cfg")
    device="${name%.cfg}"
    diff -u "$cfg" "/app/configs_fixed/$name" > "/app/diffs/${device}.diff" || true
done

# Validate drift report against JSON Schema
python3 -c "
import json
from jsonschema import validate
with open('/app/drift_report.json') as f:
    report = json.load(f)
with open('/app/schema/drift_report.schema.json') as f:
    schema = json.load(f)
validate(instance=report, schema=schema)
print('Schema validation passed')
"
