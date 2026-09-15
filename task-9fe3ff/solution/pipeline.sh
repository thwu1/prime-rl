#!/bin/bash
#
# Pipeline: optimize, visualize (graphviz), plot convergence (gnuplot),
#           evaluate, covariance recovery, consistency analysis.
set -e

GRAPH="${1:?Usage: pipeline.sh <g2o_file> <config_yaml> <output_dir>}"
CONFIG="${2:?Missing config file}"
OUTDIR="${3:?Missing output directory}"

mkdir -p "$OUTDIR"

# Step 1: Run the optimizer
python3 /app/optimizer.py \
    --graph "$GRAPH" \
    --config "$CONFIG" \
    --output "$OUTDIR/optimized.txt"

# Step 2: Generate pose-graph DOT file and render SVG with graphviz
python3 /app/gen_dot.py "$GRAPH" "$OUTDIR/optimized.txt" "$OUTDIR/graph.dot"
dot -Tsvg "$OUTDIR/graph.dot" -o "$OUTDIR/graph.svg"

# Step 3: Extract cost history from JSON report, plot with gnuplot
jq -r '.cost_history | to_entries[] | [.key, .value] | @tsv' \
    "$OUTDIR/optimized.txt.report" > "$OUTDIR/cost_data.tsv"

GPSCRIPT="$OUTDIR/convergence.gp"
printf 'set terminal png size 800,600\n' > "$GPSCRIPT"
printf 'set output "%s/convergence.png"\n' "$OUTDIR" >> "$GPSCRIPT"
printf 'set title "Optimization Convergence"\n' >> "$GPSCRIPT"
printf 'set xlabel "Iteration"\n' >> "$GPSCRIPT"
printf 'set ylabel "Cost"\n' >> "$GPSCRIPT"
printf 'set grid\n' >> "$GPSCRIPT"
printf 'plot "%s/cost_data.tsv" using 1:2 with linespoints title "Cost" lw 2\n' "$OUTDIR" >> "$GPSCRIPT"
gnuplot "$GPSCRIPT"

# Step 4: Trajectory evaluation against ground truth
python3 /app/evaluate.py \
    --estimated "$OUTDIR/optimized.txt" \
    --reference /app/graphs/ground_truth.txt \
    --output "$OUTDIR/evaluation.json"

# Step 5: Marginal covariance recovery
python3 /app/covariance.py \
    --graph "$GRAPH" \
    --poses "$OUTDIR/optimized.txt" \
    --output "$OUTDIR/covariance.json"

# Step 6: Edge consistency analysis
python3 /app/consistency.py \
    --graph "$GRAPH" \
    --poses "$OUTDIR/optimized.txt" \
    --threshold 7.815 \
    --output "$OUTDIR/consistency.json"

echo "Pipeline complete. Results in $OUTDIR/"
