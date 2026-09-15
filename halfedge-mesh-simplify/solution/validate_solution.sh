#!/usr/bin/env bash
# Validate all output meshes using mesh_stats.py and jq
#

FAIL=0
COUNT=0

for obj in /app/output/*.obj; do
    [ -f "$obj" ] || continue
    COUNT=$((COUNT + 1))

    STATS=$(python3 /app/mesh_stats.py "$obj")
    VALID=$(echo "$STATS" | jq -r '.is_valid')
    EULER=$(echo "$STATS" | jq -r '.euler_characteristic')
    FACES=$(echo "$STATS" | jq -r '.face_count')

    if [ "$VALID" != "true" ]; then
        echo "FAIL: $obj is_valid=$VALID"
        FAIL=1
    fi
    if [ "$EULER" != "2" ]; then
        echo "FAIL: $obj euler_characteristic=$EULER (expected 2)"
        FAIL=1
    fi
    if [ "$FACES" -lt 4 ] 2>/dev/null; then
        echo "FAIL: $obj face_count=$FACES < 4"
        FAIL=1
    fi

    if [ $FAIL -eq 0 ]; then
        echo "OK: $obj (faces=$FACES, euler=$EULER, valid=$VALID)"
    fi
done

if [ $COUNT -eq 0 ]; then
    echo "FAIL: no output meshes found in /app/output/"
    exit 1
fi

if [ $FAIL -ne 0 ]; then
    echo "Validation FAILED"
    exit 1
fi

echo "All $COUNT meshes validated successfully"
exit 0
