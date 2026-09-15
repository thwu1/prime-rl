#!/bin/bash


# Step 1: Run conformance audit to produce the report
echo "=== Running conformance audit ==="
python3 /solution/audit.py

# Step 2: Install reference normalizer
echo "=== Installing reference normalizer ==="
cp /solution/reference_normalizer.py /app/reference_normalizer.py
chmod +x /app/reference_normalizer.py

# Step 3: Verify reference normalizer against a few key vectors
echo "=== Verifying reference normalizer ==="
PASS=0
FAIL=0

check() {
    local input="$1"
    local expected="$2"
    local desc="$3"
    local got
    got=$(echo "$input" | python3 /app/reference_normalizer.py)
    if [ "$got" = "$expected" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $desc — expected $expected, got $got"
    fi
}

check "fb7ff8000000000000" "f97e00" "f64 NaN -> canonical f16"
check "fa80000000" "f98000" "f32 -0.0 -> f16 preserving sign"
check "18ff" "18ff" "uint 255 stays u8"
check "1900ff" "18ff" "uint 255 from u16 -> u8"
check "fb40f86a0000000000" "fa47c35000" "f64 100000.0 -> f32"
check "9f010203ff" "83010203" "indef array -> definite"
check "bf616101616202ff" "a2616101616202" "indef map -> definite"
check "a21903e801617a02" "a21903e801617a02" "bytewise-lex map order"
check "a2617a021903e801" "a21903e801617a02" "reversed map -> bytewise-lex"
check "db000000000000000100" "c100" "tag u64(1) -> inline"

echo "Verification: $PASS passed, $FAIL failed"
