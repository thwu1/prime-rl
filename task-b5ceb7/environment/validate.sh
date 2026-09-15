#!/bin/bash
# Validate simulator output against reference profiling data.
# Queries reference metrics from SQLite and parses simulator JSON output with jq.
cd /app

if [ ! -f sim_output.json ]; then
    echo "ERROR: sim_output.json not found. Run the simulator first."
    exit 1
fi

echo "=== Validation ==="

PASS=0
FAIL=0

KERNELS=$(sqlite3 profiling.db "SELECT kernel_name FROM reference_metrics ORDER BY kernel_name;")

for kernel in $KERNELS; do
    exp_wf=$(sqlite3 profiling.db "SELECT wavefronts FROM reference_metrics WHERE kernel_name='$kernel';")
    exp_tc=$(sqlite3 profiling.db "SELECT total_conflicts FROM reference_metrics WHERE kernel_name='$kernel';")
    exp_cf_int=$(sqlite3 profiling.db "SELECT conflict_free FROM reference_metrics WHERE kernel_name='$kernel';")

    if [ "$exp_cf_int" = "1" ]; then exp_cf="true"; else exp_cf="false"; fi

    act_wf=$(jq -r ".\"$kernel\".wavefronts" sim_output.json)
    act_tc=$(jq -r ".\"$kernel\".total_conflicts" sim_output.json)
    act_cf=$(jq -r ".\"$kernel\".conflict_free" sim_output.json)

    if [ "$act_wf" = "null" ]; then
        echo "MISSING: $kernel (not in simulator output)"
        FAIL=$((FAIL + 1))
        continue
    fi

    if [ "$act_wf" = "$exp_wf" ] && [ "$act_tc" = "$exp_tc" ] && [ "$act_cf" = "$exp_cf" ]; then
        echo "PASS: $kernel"
        PASS=$((PASS + 1))
    else
        echo "FAIL: $kernel"
        [ "$act_wf" != "$exp_wf" ] && echo "  wavefronts: got $act_wf, expected $exp_wf"
        [ "$act_tc" != "$exp_tc" ] && echo "  total_conflicts: got $act_tc, expected $exp_tc"
        [ "$act_cf" != "$exp_cf" ] && echo "  conflict_free: got $act_cf, expected $exp_cf"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "Results: $PASS/$((PASS + FAIL)) passed"
if [ $FAIL -gt 0 ]; then
    exit 1
fi
echo "ALL CHECKS PASSED"
