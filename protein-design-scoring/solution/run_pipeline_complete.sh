#!/bin/bash
set -euo pipefail

CONFIG="/app/config.json"

# ============================================================
# Stage 1: Normalize PAE JSON files
# ============================================================
mkdir -p /app/pae_normalized

for f in /app/pae/*_pae.json; do
    design=$(basename "$f" _pae.json)
    jq 'if type == "array" then .[0].predicted_aligned_error else .pae end' \
        "$f" > "/app/pae_normalized/${design}.json"
done

# ============================================================
# Stage 2: Compute structural metrics
# ============================================================
python3 /app/metrics.py "$CONFIG"

# ============================================================
# Stage 3: Load metrics into SQLite and compute ranking
# ============================================================
rm -f /app/designs.db
sqlite3 /app/designs.db < /app/pipeline.sql

# ============================================================
# Stage 4: Export ranked results as JSON
# ============================================================
python3 -c "
import sqlite3, json

db = sqlite3.connect('/app/designs.db')
db.row_factory = sqlite3.Row
rows = db.execute(
    'SELECT * FROM ranked_designs ORDER BY composite_score DESC'
).fetchall()

designs = {}
ranking = []
for r in rows:
    name = r['design']
    ranking.append(name)
    designs[name] = {
        'rmsd': round(r['rmsd'], 6),
        'lddt': round(r['lddt'], 6),
        'tm_score': round(r['tm_score'], 6),
        'gdt_ts': round(r['gdt_ts'], 6),
        'interface_contacts': int(r['interface_contacts']),
        'hotspot_coverage': round(r['hotspot_coverage'], 6),
        'interface_pae': round(r['interface_pae'], 6),
        'mean_plddt': round(r['mean_plddt'], 6),
        'composite_score': round(r['composite_score'], 6),
    }

with open('/app/results.json', 'w') as f:
    json.dump({'designs': designs, 'ranking': ranking}, f, indent=2)

db.close()
"

echo "Pipeline complete. Results written to /app/results.json"
