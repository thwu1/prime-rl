#!/bin/bash
TB=/app/tb/tb_verify.v
GOLDEN=/app/rtl/timer_apb.v
MUTDIR=/app/mutants

if [ ! -f "$TB" ]; then
    echo "ERROR: Testbench not found at $TB"
    exit 1
fi

echo "=== Golden RTL ==="
iverilog -o /tmp/golden_sim "$GOLDEN" "$TB" 2>&1
if [ $? -ne 0 ]; then
    echo "GOLDEN: COMPILATION FAILED"
    exit 1
fi
golden_out=$(vvp /tmp/golden_sim 2>&1)
echo "$golden_out"
if echo "$golden_out" | grep -q "ALL TESTS PASSED"; then
    echo "GOLDEN: PASS"
else
    echo "GOLDEN: FAIL — testbench does not pass on golden RTL"
    exit 1
fi

echo ""
echo "=== Mutation Testing ==="
killed=0
survived=0
total=0

for m in "$MUTDIR"/mutant_*.v; do
    total=$((total + 1))
    name=$(basename "$m" .v)
    printf "  %-12s " "$name:"

    iverilog -o "/tmp/${name}_sim" "$m" "$TB" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "KILLED (compile error)"
        killed=$((killed + 1))
        continue
    fi

    mout=$(vvp "/tmp/${name}_sim" 2>/dev/null)
    if echo "$mout" | grep -q "\[FAIL\]"; then
        echo "KILLED"
        killed=$((killed + 1))
    else
        echo "SURVIVED"
        survived=$((survived + 1))
    fi
done

echo ""
echo "=== Score: $killed/$total killed ==="
if [ $survived -eq 0 ]; then
    echo "100% mutation coverage"
else
    echo "$survived mutant(s) survived — improve your testbench"
fi
