#!/bin/bash

cd /app

# Step 1: Run the optimization solver (computes swaps, inserts into DB, generates DOT)
python3 /solution/solver.py

# Step 2: Generate audit report using sqlite3 JSON mode + jq
mkdir -p /app/reports
sqlite3 /app/netops.db -json "
SELECT t.topology_id as id, t.name, t.node_count,
       o.original_diameter, o.min_diameter as optimized_diameter,
       o.remove_src, o.remove_dst, o.add_src, o.add_dst
FROM topologies t
JOIN optimization_results o ON t.topology_id = o.topology_id
ORDER BY t.topology_id
" | jq '{topologies: [.[] | {id, name, node_count, original_diameter, optimized_diameter, swap: {remove_src, remove_dst, add_src, add_dst}}]}' > /app/reports/audit.json

# Step 3: Render topology change visualization DOT -> SVG
dot -Tsvg /app/reports/topology_changes.dot -o /app/reports/topology_changes.svg

echo "All deliverables complete."
