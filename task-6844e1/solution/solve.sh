#!/bin/bash

# Solution: fix simulator bugs, implement throttle controller, generate artifacts.

set -e

cd /app

# Step 1: Apply all fixes (throttle implementation + simulator bug fixes)
python3 /solution/apply_fixes.py

# Step 2: Run the simulation
python3 /app/run.py

# Step 3: Generate convergence plot using gnuplot
gnuplot /app/plot_template.gp

# Step 4: Generate analysis JSON
python3 /solution/analyze.py

echo ""
echo "Solution complete. Artifacts:"
ls -la /app/results/
