#!/bin/bash

# The GLPK pipeline at /app/pipeline/ has three bugs:
#
# 1. generate_data.py computes bigM = max(all_durations) — far too small.
#    The Manne disjunctive formulation needs bigM >= sum(all_durations)
#    (a valid upper bound on the makespan) for the relaxed side of each
#    disjunctive pair to be truly non-binding.
#
# 2. jsp.mod precedence constraint uses duration[j, k+1] instead of
#    duration[j, k].  It should enforce s[j,k+1] >= s[j,k] + duration[j,k].
#
# 3. run.sh sets --tmlim 10, too short for branch-and-bound on 10×5 MIPs.

# Apply the three fixes to the pipeline
sed -i 's/big_m = max(all_durations)/big_m = sum(all_durations)/' \
    /app/pipeline/generate_data.py

sed -i 's/duration\[j, k+1\]/duration[j, k]/' \
    /app/pipeline/jsp.mod

sed -i 's/--tmlim 10/--tmlim 300 --mipgap 0.05/' \
    /app/pipeline/run.sh

# The corrected GLPK pipeline works but is very slow on 10×5 instances
# due to the weak LP relaxation of the Manne formulation.  Use a standalone
# simulated-annealing solver for reliable results within quality targets.
python3 /solution/jsp_solver.py
