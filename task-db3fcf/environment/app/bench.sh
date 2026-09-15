#!/bin/bash
#
# Benchmark: compile all MiniCalc programs and report instruction counts.
# Uses: python3 (compiler), jq (JSON processing), gawk (text formatting)
#
# Usage:
#   bench.sh                     — show instruction counts for unoptimized bytecode
#   bench.sh /app/optimizer.py   — compare original vs optimized instruction counts

set -euo pipefail

PROGRAMS_DIR="/opt/minicalc/programs"

if [ -n "${1:-}" ]; then
    OPTIMIZER="$1"
    echo "=== MiniCalc Bytecode Benchmark (with optimizer: $OPTIMIZER) ==="
    echo ""
    for f in "$PROGRAMS_DIR"/*.mc; do
        name=$(basename "$f" .mc)
        orig="/tmp/_bench_${name}.json"
        opt="/tmp/_bench_${name}_opt.json"
        python3 /opt/minicalc/compile_program.py "$f" "$orig" 2>/dev/null
        orig_main=$(jq '.main | length' "$orig")
        orig_func=$(jq '[.functions | to_entries[] | .value.code | length] | add // 0' "$orig")
        python3 "$OPTIMIZER" "$orig" "$opt" 2>/dev/null
        opt_main=$(jq '.main | length' "$opt")
        opt_func=$(jq '[.functions | to_entries[] | .value.code | length] | add // 0' "$opt")
        orig_total=$((orig_main + orig_func))
        opt_total=$((opt_main + opt_func))
        printf "%s\t%d\t%d\n" "$name" "$orig_total" "$opt_total"
        rm -f "$orig" "$opt"
    done | gawk -F'\t' '{
        pct = ($2 > 0) ? (($2 - $3) / $2 * 100) : 0
        printf "%-24s orig=%-5d opt=%-5d reduction=%5.1f%%\n", $1, $2, $3, pct
        total_orig += $2
        total_opt += $3
    } END {
        pct = (total_orig > 0) ? ((total_orig - total_opt) / total_orig * 100) : 0
        printf "\n%-24s orig=%-5d opt=%-5d reduction=%5.1f%%\n", "TOTAL", total_orig, total_opt, pct
    }'
else
    echo "=== MiniCalc Bytecode Instruction Counts ==="
    echo ""
    for f in "$PROGRAMS_DIR"/*.mc; do
        name=$(basename "$f" .mc)
        tmp="/tmp/_bench_${name}.json"
        python3 /opt/minicalc/compile_program.py "$f" "$tmp" 2>/dev/null
        main_len=$(jq '.main | length' "$tmp")
        func_len=$(jq '[.functions | to_entries[] | .value.code | length] | add // 0' "$tmp")
        total=$((main_len + func_len))
        printf "%s\t%d\t%d\t%d\n" "$name" "$main_len" "$func_len" "$total"
        rm -f "$tmp"
    done | gawk -F'\t' '{
        printf "%-24s main=%-5d func=%-5d total=%-5d\n", $1, $2, $3, $4
        grand += $4
    } END {
        printf "\n%-24s %23s %-5d\n", "GRAND_TOTAL", "", grand
    }'
fi
