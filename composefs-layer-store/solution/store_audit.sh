#!/bin/bash
#
# Store audit script — independently validates a content-addressed store
# using jq, find, and sha256sum.
# Usage: store-audit.sh <store-dir> <manifests-dir>

set -u

STORE_DIR="$1"
MANIFESTS_DIR="$2"

REF_FILE=$(mktemp)
ALL_FILE=$(mktemp)
trap 'rm -f "$REF_FILE" "$ALL_FILE"' EXIT

# Count total objects using find
TOTAL_OBJECTS=0
if [ -d "$STORE_DIR/objects" ]; then
    TOTAL_OBJECTS=$(find "$STORE_DIR/objects" -type f | wc -l | tr -d ' ')
fi

# Extract all referenced sha256 digests using jq
for manifest in "$MANIFESTS_DIR"/*.json; do
    [ -f "$manifest" ] || continue
    jq -r '.entries[] | select(.type == "file" and .sha256 != null) | .sha256' "$manifest" 2>/dev/null
done | sort -u > "$REF_FILE"

REFERENCED_OBJECTS=$(wc -l < "$REF_FILE" | tr -d ' ')

# List all object hashes in store using find + basename
if [ -d "$STORE_DIR/objects" ]; then
    find "$STORE_DIR/objects" -type f -exec basename {} \; | sort -u > "$ALL_FILE"
else
    : > "$ALL_FILE"
fi

# Count orphans (in store but not referenced)
ORPHANED_OBJECTS=$(comm -23 "$ALL_FILE" "$REF_FILE" | wc -l | tr -d ' ')

# Verify integrity of each referenced object using sha256sum
INTEGRITY_ERRORS=0
while IFS= read -r digest; do
    [ -z "$digest" ] && continue
    prefix="${digest:0:2}"
    obj_path="$STORE_DIR/objects/$prefix/$digest"
    if [ -f "$obj_path" ]; then
        actual=$(sha256sum "$obj_path" | cut -d' ' -f1)
        if [ "$actual" != "$digest" ]; then
            INTEGRITY_ERRORS=$((INTEGRITY_ERRORS + 1))
        fi
    else
        INTEGRITY_ERRORS=$((INTEGRITY_ERRORS + 1))
    fi
done < "$REF_FILE"

# Determine status and exit code
if [ "$INTEGRITY_ERRORS" -gt 0 ]; then
    STATUS="errors_found"
    EXIT_CODE=1
else
    STATUS="ok"
    EXIT_CODE=0
fi

# Output JSON report
printf '{"total_objects": %d, "referenced_objects": %d, "orphaned_objects": %d, "integrity_errors": %d, "status": "%s"}\n' \
    "$TOTAL_OBJECTS" "$REFERENCED_OBJECTS" "$ORPHANED_OBJECTS" "$INTEGRITY_ERRORS" "$STATUS"

exit $EXIT_CODE
