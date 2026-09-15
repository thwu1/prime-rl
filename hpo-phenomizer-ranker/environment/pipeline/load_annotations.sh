#!/bin/bash
# Load disease-phenotype annotations into the SQLite database.
# Uses AWK to parse the HPOA file and generate SQL INSERT statements.
#
# Usage: load_annotations.sh <database.db> <annotations.hpoa>

set -e

DB="$1"
ANNOT="$2"

if [ -z "$DB" ] || [ -z "$ANNOT" ]; then
    echo "Usage: $0 <database.db> <annotations.hpoa>" >&2
    exit 1
fi

# Generate and execute SQL from the HPOA file
awk -f /app/pipeline/process_annotations.awk "$ANNOT" | sqlite3 "$DB"

# Report loaded counts
TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM annotations;")
DISEASES=$(sqlite3 "$DB" "SELECT COUNT(DISTINCT disease_id) FROM annotations;")
echo "Loaded $TOTAL annotation rows for $DISEASES diseases."
