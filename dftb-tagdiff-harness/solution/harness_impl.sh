#!/usr/bin/env bash
#
# harness.sh — Run tagdiff comparison across all test case directories.

set -uo pipefail

PASS=0
FAIL=0

# Clear previous detail log
> /app/detail.log

for testdir in /app/testcases/*/; do
    testname=$(basename "$testdir")
    ref="$testdir/_autotest.tag"
    new="$testdir/autotest.tag"

    if [[ ! -f "$ref" ]] || [[ ! -f "$new" ]]; then
        echo "SKIP $testname: missing files"
        continue
    fi

    # Chain local config (if present) before global config
    config_args=()
    if [[ -f "$testdir/tagdiff.conf" ]]; then
        config_args+=("-c" "$testdir/tagdiff.conf")
    fi
    config_args+=("-c" "/app/tagdiff.conf")

    echo "=== $testname ==="
    /app/tagdiff.sh "${config_args[@]}" "$ref" "$new"
    rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "RESULT: PASS"
        PASS=$((PASS + 1))
        echo "$testname PASS" >> /app/detail.log
    else
        echo "RESULT: FAIL"
        FAIL=$((FAIL + 1))
        echo "$testname FAIL" >> /app/detail.log
    fi
    echo ""
done

TOTAL=$((PASS + FAIL))
echo "================================"
echo "SUMMARY: $PASS passed, $FAIL failed out of $TOTAL"

cat > /app/results.json << EOF
{"passed": $PASS, "failed": $FAIL, "total": $TOTAL}
EOF

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
exit 0
