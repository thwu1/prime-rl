#!/bin/bash
#
# harness.sh - Cross-compiler differential testing harness
#
# Generates N random C programs, compiles each with gcc and clang at
# -O0 and -O2, runs them, and compares CRC32 checksums. Any mismatch
# indicates that the safe math wrappers have leaked undefined behavior.
#
# Usage: ./harness.sh [num_tests]
#

NUM_TESTS=${1:-100}
TIMEOUT_SEC=10
PASS=0
FAIL=0

COMPILERS="gcc clang"
OPT_LEVELS="-O0 -O2"

# Build the expression generator
echo "Building expression generator..."
make -C /app expr_gen 2>&1
if [ $? -ne 0 ]; then
    echo "FATAL: Failed to build expr_gen"
    exit 2
fi

echo "Running $NUM_TESTS cross-compiler differential tests..."

for seed in $(seq 1 "$NUM_TESTS"); do
    PROG="/tmp/harness_test_${seed}.c"

    # Generate test program
    /app/expr_gen "$seed" > "$PROG"
    if [ $? -ne 0 ]; then
        echo "FAIL: seed $seed - expr_gen failed"
        FAIL=$((FAIL + 1))
        continue
    fi

    REFERENCE=""
    MISMATCH=0

    for cc in $COMPILERS; do
        for opt in $OPT_LEVELS; do
            TAG="${cc}$(echo $opt | tr -d '-')"
            EXE="/tmp/harness_${seed}_${TAG}"

            # Compile with selected compiler and optimization level
            $cc $opt -std=c11 -I/app "$PROG" -o "$EXE" 2>/dev/null
            if [ $? -ne 0 ]; then
                echo "FAIL: seed $seed - $cc $opt compilation failed"
                MISMATCH=1
                break 2
            fi

            # Run
            OUT=$(timeout "$TIMEOUT_SEC" "$EXE" 2>/dev/null)
            if [ $? -ne 0 ]; then
                echo "FAIL: seed $seed - $cc $opt runtime error"
                MISMATCH=1
                break 2
            fi

            if [ -z "$REFERENCE" ]; then
                REFERENCE="$OUT"
            elif [ "$OUT" != "$REFERENCE" ]; then
                echo "FAIL: seed $seed - mismatch at $cc $opt: got '$OUT', expected '$REFERENCE'"
                MISMATCH=1
            fi
        done
    done

    if [ $MISMATCH -eq 0 ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
    fi

    rm -f "$PROG" /tmp/harness_${seed}_*
done

echo ""
echo "=== Results: $PASS passed, $FAIL failed out of $NUM_TESTS tests ==="

if [ $FAIL -eq 0 ]; then
    echo "ALL TESTS PASSED"
    exit 0
else
    echo "SOME TESTS FAILED"
    exit 1
fi
