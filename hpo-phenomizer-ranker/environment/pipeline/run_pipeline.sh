#!/bin/bash
# HPO Phenomizer Pipeline — builds the database and runs example queries.
#
# This script orchestrates the full pipeline:
#   1. Parse ontology OBO file into SQLite graph
#   2. Load annotations from HPOA file
#   3. Query similarity using the scoring module
#
# Usage: bash /app/pipeline/run_pipeline.sh
set -e

CONFIG="/app/pipeline/config.json"

# Read paths from config
DB=$(python3 -c "import json; print(json.load(open('$CONFIG'))['database_path'])")
OBO=$(python3 -c "import json; print(json.load(open('$CONFIG'))['ontology_path'])")
ANNOT=$(python3 -c "import json; print(json.load(open('$CONFIG'))['annotation_path'])")

echo "=== HPO Phenomizer Pipeline ==="
echo "Database: $DB"
echo "Ontology: $OBO"
echo "Annotations: $ANNOT"
echo ""

# Step 1: Build ontology graph
echo "--- Step 1: Building ontology graph ---"
rm -f "$DB"
python3 /app/pipeline/obo_graph.py "$OBO" "$DB"
echo "Terms: $(sqlite3 "$DB" 'SELECT COUNT(*) FROM terms')"
echo "Parent relations: $(sqlite3 "$DB" 'SELECT COUNT(*) FROM parents')"
echo "Ancestor pairs: $(sqlite3 "$DB" 'SELECT COUNT(*) FROM ancestors')"
echo ""

# Step 2: Load annotations
echo "--- Step 2: Loading annotations ---"
bash /app/pipeline/load_annotations.sh "$DB" "$ANNOT"
echo ""

# Step 3: Example queries
echo "--- Step 3: Example queries ---"
echo "IC of HP:0000252 (Microcephaly):"
python3 /app/pipeline/similarity.py --db "$DB" ic HP:0000252
echo ""

echo "Resnik similarity HP:0000252 vs HP:0000256:"
python3 /app/pipeline/similarity.py --db "$DB" similarity HP:0000252 HP:0000256 resnik
echo ""

echo "Disease ranking (resnik + funsimavg):"
python3 /app/pipeline/similarity.py --db "$DB" rank "HP:0001250,HP:0000252,HP:0001290" \
    --method resnik --combiner funsimavg
echo ""
echo "Pipeline complete."
