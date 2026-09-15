#!/bin/bash

export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export PYTHONIOENCODING=utf-8

# Copy the solution runner into place
cp /solution/runner.py /app/sqllogictest_runner.py
chmod +x /app/sqllogictest_runner.py

# Verify it works on all test files
echo "=== Verifying solution ==="
PASS=0
FAIL=0
for f in /app/test_files/01_basic.test /app/test_files/02_sorting.test \
         /app/test_files/03_nulls.test /app/test_files/04_hashing.test \
         /app/test_files/05_loops.test /app/test_files/06_regex.test \
         /app/test_files/07_labels.test /app/test_files/08_error_matching.test \
         /app/test_files/09_require_skip.test /app/test_files/10_combined.test \
         /app/test_files/11_connections.test /app/test_files/12_explain_verify.test \
         /app/test_files/13_reconnect.test /app/test_files/14_interactions.test \
         /app/test_files/15_mode_verify.test /app/test_files/16_mode_skip.test; do
    if python3 /app/sqllogictest_runner.py "$f" > /dev/null 2>&1; then
        echo "PASS: $(basename $f)"
        PASS=$((PASS + 1))
    else
        echo "FAIL: $(basename $f)"
        FAIL=$((FAIL + 1))
    fi
done

# Verify failure detection
for f in /app/test_files/fail_wrong_result.test /app/test_files/fail_bad_error.test; do
    if python3 /app/sqllogictest_runner.py "$f" > /dev/null 2>&1; then
        echo "FAIL: $(basename $f) should have failed but passed"
        FAIL=$((FAIL + 1))
    else
        echo "PASS: $(basename $f) correctly detected failure"
        PASS=$((PASS + 1))
    fi
done

echo "=== Results: $PASS passed, $FAIL failed ==="
