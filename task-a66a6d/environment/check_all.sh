#!/bin/bash
#
# Verify dbt_select.py against reference outputs.

PASS=0
FAIL=0

check() {
    local label="$1"
    local expected_file="$2"
    shift 2
    local actual expected
    actual=$(python3 /app/dbt_select.py "$@" 2>/dev/null)
    expected=$(cat "$expected_file")
    if [ "$actual" = "$expected" ]; then
        echo "PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "FAIL: $label"
        echo "  Run manually: python3 /app/dbt_select.py $*"
        echo "  Compare with: $expected_file"
        FAIL=$((FAIL + 1))
    fi
}

check "q01: plain name"              /app/expected/q01.txt --select stg_customers
check "q02: unlimited ancestors"     /app/expected/q02.txt --select +int_customer_orders
check "q03: unlimited descendants"   /app/expected/q03.txt --select int_product_sales+
check "q04: depth-limited ancestors" /app/expected/q04.txt --select 1+mart_customers
check "q05: depth-limited descendants" /app/expected/q05.txt --select stg_orders+1
check "q06: @ full subgraph"         /app/expected/q06.txt --select @int_regional_sales
check "q07: tag selector"            /app/expected/q07.txt --select tag:critical
check "q08: config selector"         /app/expected/q08.txt --select config.materialized:table
check "q09: tag with exclude"        /app/expected/q09.txt --select tag:daily --exclude tag:staging
check "q10: comma intersection"      /app/expected/q10.txt --select "+mart_customers,tag:critical"
check "q11: source selector"         /app/expected/q11.txt --select source:raw.orders
check "q12: fqn selector"            /app/expected/q12.txt --select fqn:analytics.intermediate.int_regional_sales
check "q13: multi-select union"      /app/expected/q13.txt --select tag:static --select source:raw.orders

echo ""
echo "Results: $PASS/13 passed, $FAIL/13 failed"
[ $FAIL -eq 0 ]
