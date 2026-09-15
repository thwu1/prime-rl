#!/bin/bash

set -e

cd /app

# Step 1: Run configuration compliance analysis
echo "=== Step 1: Analyzing configurations ==="
python3 /solution/analyzer.py

# Step 2: Generate remediation patches using diff
echo "=== Step 2: Generating remediation patches ==="
python3 /solution/remediator.py

# Step 3: Generate migration plan
echo "=== Step 3: Generating migration plan ==="
python3 /solution/planner.py

# Step 4: Generate topology diagram with Graphviz
echo "=== Step 4: Generating topology diagram ==="
python3 /solution/topology_gen.py
dot -Tsvg /app/topology.dot -o /app/topology.svg
echo "SVG rendered to /app/topology.svg"

# Verify all deliverables exist
echo ""
echo "=== Verification ==="
for f in /app/audit_report.json /app/migration_plan.json /app/topology.dot /app/topology.svg; do
    if [ -f "$f" ]; then
        echo "OK: $f"
    else
        echo "MISSING: $f"
    fi
done

PATCH_COUNT=$(ls /app/remediation_patches/*.patch 2>/dev/null | wc -l)
echo "Patches generated: $PATCH_COUNT"

# Show summary using jq
echo ""
echo "=== Audit Summary ==="
jq '.summary' /app/audit_report.json
echo "Total defects: $(jq '.total_defects' /app/audit_report.json)"
echo ""
echo "=== Migration Phases ==="
jq '.[].phase' /app/migration_plan.json
