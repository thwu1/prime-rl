#!/bin/bash

set -e

# Keep the reference solution hermetic. The original downloaded FlameGraph's
# Perl helpers at runtime, which fails in images without curl and makes oracle
# correctness depend on GitHub availability.
python3 /solution/collapse_perf.py \
    /app/incident/perf/perf_script.txt /tmp/folded.txt
python3 /solution/gen_flamegraph.py /tmp/folded.txt /app/flamegraph.svg

# Run analysis on folded stacks + other incident data
python3 /solution/analyze.py --folded /tmp/folded.txt
