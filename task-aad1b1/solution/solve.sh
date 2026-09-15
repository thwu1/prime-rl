#!/bin/bash

cd /app

# Make bisect helper scripts executable
chmod +x /solution/bisect_identity.sh /solution/bisect_diff.sh

# Step 1: Find regression commits using git bisect
FIRST_COMMIT=$(git log --reverse --format='%H' | head -1)

# Bisect for identity/compaction regression (issues 001, 002)
git bisect start HEAD "$FIRST_COMMIT" 2>&1 >/dev/null
git bisect run /solution/bisect_identity.sh 2>&1 >/dev/null
IDENTITY_BAD=$(git rev-parse refs/bisect/bad 2>/dev/null || echo "unknown")
git bisect reset 2>&1 >/dev/null

# Bisect for diff regression (issue 003)
git bisect start HEAD "$FIRST_COMMIT" 2>&1 >/dev/null
git bisect run /solution/bisect_diff.sh 2>&1 >/dev/null
DIFF_BAD=$(git rev-parse refs/bisect/bad 2>/dev/null || echo "unknown")
git bisect reset 2>&1 >/dev/null

# Step 2: Generate profiling call graph via cProfile + gprof2dot + graphviz
python3 -m cProfile -o /app/profile.pstats benchmarks/profile_target.py 2>/dev/null || true
if command -v gprof2dot >/dev/null 2>&1 && command -v dot >/dev/null 2>&1; then
    gprof2dot -f pstats /app/profile.pstats 2>/dev/null | dot -Tsvg -o /app/callgraph.svg 2>/dev/null || true
fi

# Step 3: Write regression report from bisect results
python3 /solution/write_report.py "$IDENTITY_BAD" "$DIFF_BAD"

# Step 4: Apply all fixes and merge implementation
cp /solution/persistent_map_fixed.py /app/store/persistent_map.py
