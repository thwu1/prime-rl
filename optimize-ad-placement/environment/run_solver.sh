#!/bin/bash

# Quick solver evaluation without database tracking.
# For full benchmarking with SQLite experiment tracking, use:
#   make -C /app benchmark    # run solver, store results, output JSON
#   make -C /app analyze      # query per-case results
#   make -C /app by-type      # aggregate by distribution type
#   make -C /app worst        # show worst-performing cases

if [ ! -f /app/solver.py ]; then
    echo "ERROR: /app/solver.py not found."
    echo "Create a solver that reads from stdin and writes to stdout."
    exit 1
fi

echo "Running solver on all test cases..."
echo ""

total=0
count=0
for inp in /app/test_cases/input_*.txt; do
    name=$(basename "$inp")
    out="${inp/input_/output_}"

    if timeout 120 python3 /app/solver.py < "$inp" > "$out" 2>/dev/null; then
        result=$(python3 /app/scorer.py "$inp" "$out" 2>/dev/null)
        if echo "$result" | grep -q "Satisfaction:"; then
            score=$(echo "$result" | grep "Satisfaction:" | awk -F: '{print $2}' | tr -d ' ')
            printf "  %s: %.6f\n" "$name" "$score"
            total=$(python3 -c "print($total + $score)")
            count=$((count + 1))
        else
            echo "  $name: VALIDATION ERROR"
        fi
    else
        echo "  $name: SOLVER ERROR or TIMEOUT"
    fi
done

echo ""
if [ $count -gt 0 ]; then
    avg=$(python3 -c "print(f'{$total / $count:.6f}')")
    echo "Average satisfaction: $avg ($count cases)"
    if python3 -c "exit(0 if $total / $count >= 0.75 else 1)"; then
        echo "PASS"
    else
        echo "FAIL (need >= 0.75)"
    fi
else
    echo "No valid results."
fi
