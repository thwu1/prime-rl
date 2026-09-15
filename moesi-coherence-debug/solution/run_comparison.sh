#!/bin/bash

set -e

TRACES_DIR="/app/traces"
SIM="/app/numa_coherence.py"
DB="/app/coherence_analysis.db"
CHART="/app/comparison_chart.svg"
OUT="/app/results.json"

# Remove stale database if present
rm -f "$DB"

# Create SQLite schema
sqlite3 "$DB" "
CREATE TABLE trace_stats (
    trace TEXT NOT NULL,
    config TEXT NOT NULL CHECK(config IN ('baseline', 'optimized')),
    total_cycles INTEGER NOT NULL,
    inter_chiplet_messages INTEGER NOT NULL,
    memory_writebacks INTEGER NOT NULL,
    PRIMARY KEY (trace, config)
);

CREATE VIEW optimization_impact AS
SELECT
    b.trace,
    b.total_cycles AS baseline_cycles,
    o.total_cycles AS optimized_cycles,
    ROUND(100.0 * (b.total_cycles - o.total_cycles) / b.total_cycles, 2) AS cycle_reduction_pct,
    b.memory_writebacks AS baseline_writebacks,
    o.memory_writebacks AS optimized_writebacks,
    CASE WHEN b.memory_writebacks > 0
        THEN ROUND(100.0 * (b.memory_writebacks - o.memory_writebacks) / b.memory_writebacks, 2)
        ELSE 0.0 END AS writeback_reduction_pct,
    b.inter_chiplet_messages AS baseline_inter_chiplet,
    o.inter_chiplet_messages AS optimized_inter_chiplet,
    CASE WHEN b.inter_chiplet_messages > 0
        THEN ROUND(100.0 * (b.inter_chiplet_messages - o.inter_chiplet_messages) / b.inter_chiplet_messages, 2)
        ELSE 0.0 END AS inter_chiplet_reduction_pct
FROM trace_stats b
JOIN trace_stats o ON b.trace = o.trace
WHERE b.config = 'baseline' AND o.config = 'optimized';
"

# Run simulations and insert results into SQLite via jq + sqlite3
for trace in "$TRACES_DIR"/*.trace; do
    name=$(basename "$trace")

    baseline=$(python3 "$SIM" "$trace" --json-stats --no-owner-opt --no-chiplet-cache)
    optimized=$(python3 "$SIM" "$trace" --json-stats)

    b_cycles=$(echo "$baseline" | jq '.total_cycles')
    b_inter=$(echo "$baseline" | jq '.inter_chiplet_messages')
    b_wb=$(echo "$baseline" | jq '.memory_writebacks')

    o_cycles=$(echo "$optimized" | jq '.total_cycles')
    o_inter=$(echo "$optimized" | jq '.inter_chiplet_messages')
    o_wb=$(echo "$optimized" | jq '.memory_writebacks')

    sqlite3 "$DB" "INSERT INTO trace_stats VALUES ('$name', 'baseline', $b_cycles, $b_inter, $b_wb);"
    sqlite3 "$DB" "INSERT INTO trace_stats VALUES ('$name', 'optimized', $o_cycles, $o_inter, $o_wb);"
done

# Generate gnuplot data from SQLite query
sqlite3 -separator ' ' "$DB" \
    "SELECT trace, baseline_cycles, optimized_cycles FROM optimization_impact ORDER BY trace;" \
    > /tmp/plot_data.dat

# Generate comparison chart with gnuplot
gnuplot <<'GNUPLOT_SCRIPT'
set terminal svg size 800,600 font "Arial,12"
set output '/app/comparison_chart.svg'
set title "NUMA Coherence: Baseline vs Optimized Total Cycles"
set xlabel "Trace" offset 0,-2
set ylabel "Total Cycles"
set style data histogram
set style histogram clustered gap 1
set style fill solid 0.8 border -1
set xtic rotate by -45 scale 0
set key left top
set bmargin 6
plot '/tmp/plot_data.dat' using 2:xtic(1) title "Baseline" lc rgb "#cc4444", \
     '' using 3 title "Optimized" lc rgb "#4444cc"
GNUPLOT_SCRIPT

# Assemble results.json by querying the SQLite database
traces_json=$(echo ".mode json
SELECT trace, config, total_cycles, inter_chiplet_messages, memory_writebacks
FROM trace_stats ORDER BY trace, config;" | sqlite3 "$DB" | jq '
  group_by(.trace) |
  map({
    (.[0].trace): (
      map({(.config): {total_cycles, inter_chiplet_messages, memory_writebacks}}) | add
    )
  }) | add
')

summary_json=$(echo ".mode json
SELECT
  ROUND(AVG(cycle_reduction_pct), 2) as avg_cycle_reduction_pct,
  ROUND(AVG(writeback_reduction_pct), 2) as avg_writeback_reduction_pct,
  ROUND(AVG(inter_chiplet_reduction_pct), 2) as avg_inter_chiplet_reduction_pct
FROM optimization_impact;" | sqlite3 "$DB" | jq '.[0]')

jq -n --argjson traces "$traces_json" --argjson summary "$summary_json" \
    '{"traces": $traces, "summary": $summary}' > "$OUT"

echo "Results written to $OUT"
echo "Database at $DB"
echo "Chart at $CHART"
