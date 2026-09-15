#!/bin/bash

set -euo pipefail

SOURCE="$1"
QUERY="$2"
OUTPUT="$3"

TMPDB=$(mktemp /tmp/mineral_lib_XXXXXX.db)
trap 'rm -f "$TMPDB"' EXIT

# Build library using Python CLI
python3 /app/mineral_id.py build-library "$SOURCE" "$TMPDB"

# Extract total count using sqlite3 CLI
TOTAL=$(sqlite3 "$TMPDB" "SELECT COUNT(*) FROM spectra;")

# Get unique mineral names sorted alphabetically via sqlite3 + jq
MINERALS=$(sqlite3 "$TMPDB" "SELECT DISTINCT name FROM spectra ORDER BY name;" \
    | jq -R . | jq -s .)

# Get wavelength distribution via sqlite3 + jq
WAVELENGTHS=$(sqlite3 -separator '|' "$TMPDB" \
    "SELECT CAST(wavelength AS TEXT), COUNT(*) FROM spectra GROUP BY wavelength;" \
    | jq -R 'split("|") | {(.[0]): (.[1] | tonumber)}' | jq -s 'add // {}')

# Run identification using Python CLI
MATCHES=$(python3 /app/mineral_id.py identify "$QUERY" --library "$TMPDB" --top 5)

# Merge all results with jq
jq -n \
    --argjson total "$TOTAL" \
    --argjson minerals "$MINERALS" \
    --argjson wavelengths "$WAVELENGTHS" \
    --argjson matches "$MATCHES" \
    '{"library_stats": {"total_spectra": $total, "unique_minerals": $minerals, "wavelengths": $wavelengths}, "identification": $matches}' \
    > "$OUTPUT"
