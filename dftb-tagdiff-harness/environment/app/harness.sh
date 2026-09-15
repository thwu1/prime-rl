#!/usr/bin/env bash
#
# harness.sh — Run tagdiff comparison across all test case directories.
# Expects /app/tagdiff.sh to exist and be executable.

set -uo pipefail

PASS=0
FAIL=0

for testdir in /app/testcases/*/; do
    testname=$(basename "$testdir")
    ref="$testdir/_autotest.tag"
    new="$testdir/autotest.tag"

    if [[ ! -f "$ref" ]] || [[ ! -f "$new" ]]; then
        echo "SKIP $testname: missing files"
        continue
    fi

    config_args=("-c" "/app/tagdiff.conf")

    echo "=== $testname ==="
    /app/tagdiff.sh "${config_args[@]}" "$ref" "$new"
    rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "RESULT: PASS"
        PASS=$((PASS + 1))
    else
        echo "RESULT: FAIL"
        FAIL=$((FAIL + 1))
    fi
    echo ""
done

TOTAL=$((PASS + FAIL))
echo "================================"
echo "SUMMARY: $PASS passed, $FAIL failed out of $TOTAL"

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
exit 0
