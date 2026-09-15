#!/bin/bash

# 1. Fix orchestrator bugs
python3 /solution/fix_orchestrator.py

# 2. Write jq filter programs
mkdir -p /app/jq_filters
cp /solution/dep_edges.jq /app/jq_filters/dep_edges.jq
cp /solution/node_attrs.jq /app/jq_filters/node_attrs.jq
cp /solution/fanout_analysis.jq /app/jq_filters/fanout_analysis.jq

# 3. Build SQLite analytical database
python3 /solution/build_db.py

# 4. Generate DOT visualization
python3 /solution/gen_dot.py
