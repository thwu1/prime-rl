#!/bin/bash
# Conformance harness: runs all tests from manifest and checks outcomes
# Uses jq to parse manifest.json

MANIFEST="/app/manifest.json"
TOOL="/app/filecheck.py"
TESTS="/app/test_inputs"

PASS=0
FAIL=0
TOTAL=0

count=$(jq '.test_cases | length' "$MANIFEST")

for i in $(seq 0 $((count - 1))); do
    name=$(jq -r ".test_cases[$i].name" "$MANIFEST")
    check=$(jq -r ".test_cases[$i].check_file" "$MANIFEST")
    input=$(jq -r ".test_cases[$i].input_file" "$MANIFEST")
    expected=$(jq -r ".test_cases[$i].expected" "$MANIFEST")
    flags=$(jq -r ".test_cases[$i].flags // [] | join(\" \")" "$MANIFEST")

    TOTAL=$((TOTAL + 1))

    if [ -n "$flags" ]; then
        python3 "$TOOL" "$TESTS/$check" --input-file "$TESTS/$input" $flags > /dev/null 2>&1
    else
        python3 "$TOOL" "$TESTS/$check" --input-file "$TESTS/$input" > /dev/null 2>&1
    fi
    actual_rc=$?

    if [ "$expected" = "pass" ] && [ $actual_rc -eq 0 ]; then
        echo "PASS: $name"
        PASS=$((PASS + 1))
    elif [ "$expected" = "fail" ] && [ $actual_rc -ne 0 ]; then
        echo "PASS: $name (correctly rejected)"
        PASS=$((PASS + 1))
    else
        echo "MISMATCH: $name (expected=$expected, exit_code=$actual_rc)"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "Conformance: $PASS/$TOTAL passed, $FAIL failed"

if [ $FAIL -gt 0 ]; then
    exit 1
fi
exit 0
