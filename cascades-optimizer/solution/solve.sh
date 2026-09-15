#!/bin/bash

set -e

# Ensure planner source is available at /app/planner
# (may be absent if /app was mounted as an empty workdir)
if [ ! -f /app/planner/cost.py ]; then
    mkdir -p /app/planner
    cp -r /opt/planner_src/planner/* /app/planner/
fi

# Apply all four fixes via a self-contained Python script.
python3 /solution/fix_planner.py
