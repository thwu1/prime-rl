#!/bin/bash
set -u
mkdir -p /app/output

# Step 1: Collapse perf script data, filter to appserver only
python3 /solution/stackcollapse.py /app/traces/baseline.perf appserver \
    > /app/output/baseline.folded
python3 /solution/stackcollapse.py /app/traces/incident.perf appserver \
    > /app/output/incident.folded

# Step 2: Generate differential folded data
python3 /solution/difffolded.py \
    /app/output/baseline.folded \
    /app/output/incident.folded > /app/output/diff.folded

# Step 3: Generate differential flame graph SVG
python3 /solution/flamegraph_gen.py /app/output/diff.folded \
    --title "Differential Flame Graph: baseline vs incident" \
    > /app/output/diff_flamegraph.svg

# Step 4: Convert off-CPU bpftrace data to folded format
python3 /solution/process_offcpu.py

# Step 5: Generate off-CPU flame graph SVG
python3 /solution/flamegraph_gen.py /app/output/offcpu.folded \
    --title "Off-CPU Flame Graph (incident)" \
    --countname microseconds \
    > /app/output/offcpu_flamegraph.svg

# Step 6: Produce the triage report
python3 /solution/triage_analyzer.py
