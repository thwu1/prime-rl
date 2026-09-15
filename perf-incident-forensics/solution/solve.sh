#!/bin/bash

set -e

# Download FlameGraph tools for perf script processing and SVG generation
mkdir -p /tmp/FlameGraph
curl -sL https://raw.githubusercontent.com/brendangregg/FlameGraph/master/stackcollapse-perf.pl \
    -o /tmp/FlameGraph/stackcollapse-perf.pl
curl -sL https://raw.githubusercontent.com/brendangregg/FlameGraph/master/flamegraph.pl \
    -o /tmp/FlameGraph/flamegraph.pl
chmod +x /tmp/FlameGraph/*.pl

# Process raw perf script through FlameGraph pipeline
/tmp/FlameGraph/stackcollapse-perf.pl /app/incident/perf/perf_script.txt > /tmp/folded.txt

# Generate flame graph SVG (try flamegraph.pl, fall back to Python generator)
if /tmp/FlameGraph/flamegraph.pl /tmp/folded.txt > /app/flamegraph.svg 2>/dev/null; then
    echo "Flame graph generated with flamegraph.pl"
else
    echo "flamegraph.pl failed, using Python SVG generator"
    python3 /solution/gen_flamegraph.py /tmp/folded.txt /app/flamegraph.svg
fi

# Run analysis on folded stacks + other incident data
python3 /solution/analyze.py --folded /tmp/folded.txt
