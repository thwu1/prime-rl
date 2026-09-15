#!/usr/bin/env bash

set -e

DB=/app/snomed.db
DATA=/app/data
rm -f "$DB"

# Locate RF2 files
CONCEPT=$(ls $DATA/sct2_Concept_Snapshot*.txt)
DESC=$(ls $DATA/sct2_Description_Snapshot*.txt)
REL=$(ls $DATA/sct2_Relationship_Snapshot*.txt)
REFSET=$(ls $DATA/der2_Refset_SimpleSnapshot*.txt 2>/dev/null || echo "")

# Create schema using sqlite3 CLI
sqlite3 "$DB" 'CREATE TABLE concepts (id TEXT, effectiveTime TEXT, active INTEGER, moduleId TEXT, definitionStatusId TEXT);'
sqlite3 "$DB" 'CREATE TABLE descriptions (id TEXT, effectiveTime TEXT, active INTEGER, moduleId TEXT, conceptId TEXT, languageCode TEXT, typeId TEXT, term TEXT, caseSignificanceId TEXT);'
sqlite3 "$DB" 'CREATE TABLE relationships (id TEXT, effectiveTime TEXT, active INTEGER, moduleId TEXT, sourceId TEXT, destinationId TEXT, relationshipGroup INTEGER, typeId TEXT, characteristicTypeId TEXT, modifierId TEXT);'
sqlite3 "$DB" 'CREATE TABLE refset_members (id TEXT, effectiveTime TEXT, active INTEGER, moduleId TEXT, refsetId TEXT, referencedComponentId TEXT);'
sqlite3 "$DB" 'CREATE TABLE transitive_closure (ancestor TEXT NOT NULL, descendant TEXT NOT NULL, PRIMARY KEY (ancestor, descendant));'

# Import RF2 data using sqlite3 .mode tabs and .import
printf '.mode tabs\n.import --skip 1 %s concepts\n' "$CONCEPT" | sqlite3 "$DB"
printf '.mode tabs\n.import --skip 1 %s descriptions\n' "$DESC" | sqlite3 "$DB"
printf '.mode tabs\n.import --skip 1 %s relationships\n' "$REL" | sqlite3 "$DB"
if [ -n "$REFSET" ]; then
    printf '.mode tabs\n.import --skip 1 %s refset_members\n' "$REFSET" | sqlite3 "$DB"
fi

# Add verhoeff_valid column and validate SCTIDs using Python helper
sqlite3 "$DB" 'ALTER TABLE concepts ADD COLUMN verhoeff_valid INTEGER DEFAULT 0;'
python3 /app/verhoeff_validate.py "$DB"

# Build transitive closure using recursive CTE in SQL
sqlite3 "$DB" "
INSERT INTO transitive_closure (ancestor, descendant)
WITH RECURSIVE tc(ancestor, descendant) AS (
    SELECT r.destinationId, r.sourceId
    FROM relationships r
    WHERE r.typeId = '116680003' AND r.active = 1
      AND r.sourceId IN (SELECT id FROM concepts WHERE active = 1 AND verhoeff_valid = 1)
      AND r.destinationId IN (SELECT id FROM concepts WHERE active = 1 AND verhoeff_valid = 1)
    UNION
    SELECT tc.ancestor, r.sourceId
    FROM tc
    JOIN relationships r ON r.destinationId = tc.descendant
    WHERE r.typeId = '116680003' AND r.active = 1
      AND r.sourceId IN (SELECT id FROM concepts WHERE active = 1 AND verhoeff_valid = 1)
)
SELECT DISTINCT ancestor, descendant FROM tc;
"

# Create indices for query performance
sqlite3 "$DB" 'CREATE INDEX idx_concepts_active ON concepts(active, verhoeff_valid);'
sqlite3 "$DB" 'CREATE INDEX idx_rel_src ON relationships(sourceId, typeId, active);'
sqlite3 "$DB" 'CREATE INDEX idx_rel_dst ON relationships(destinationId, typeId, active);'
sqlite3 "$DB" 'CREATE INDEX idx_desc_cid ON descriptions(conceptId, typeId, active);'
sqlite3 "$DB" 'CREATE INDEX idx_refset ON refset_members(refsetId, active);'
sqlite3 "$DB" 'CREATE INDEX idx_tc_anc ON transitive_closure(ancestor);'
sqlite3 "$DB" 'CREATE INDEX idx_tc_desc ON transitive_closure(descendant);'

echo "Database created at $DB"
