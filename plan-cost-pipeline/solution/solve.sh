#!/bin/bash


# Fix all 7 bugs across the multi-tool CEB evaluation pipeline.

# Fix 1+2: Replace costs.jq with corrected version
# - Adds zero clamping on all cardinalities (fixes div-by-zero on q004)
# - Fixes NILJ formula: when len1==1, uses c2t+nilj*c1t instead of c1t+nilj*c2t
cp /solution/fixed_costs.jq /app/lib/costs.jq

# Fix 3: analyze.sh - q-error redirect > should be >>
# The > overwrites on each iteration, losing all but the last query's q-errors
sed -i 's|_costs.json" > "$WORK_DIR/all_qerrors.txt"|_costs.json" >> "$WORK_DIR/all_qerrors.txt"|' /app/analyze.sh

# Fix 4: analyze.sh - planner argument order is reversed
# Script passes (output, input) but planner expects (input, output)
sed -i 's|planner.py "$WORK_DIR/${qname}_plan.json" "$WORK_DIR/${qname}_costs.json"|planner.py "$WORK_DIR/${qname}_costs.json" "$WORK_DIR/${qname}_plan.json"|' /app/analyze.sh

# Fix 5: planner.py - est_plan_true_cost uses est_costs instead of true_costs
# The estimated plan's reported cost must be computed with TRUE cardinalities
sed -i 's/if edge_key in est_costs:/if edge_key in true_costs:/' /app/lib/planner.py
sed -i 's/est_plan_true_cost += est_costs\[edge_key\]/est_plan_true_cost += true_costs[edge_key]/' /app/lib/planner.py

# Fix 6+7: Replace stats.awk with corrected version
# - Adds FS = "|" so pipe-delimited input is properly split
# - Fixes percentile to use linear interpolation instead of ceiling
cp /solution/fixed_stats.awk /app/lib/stats.awk
