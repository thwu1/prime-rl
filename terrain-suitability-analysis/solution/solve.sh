#!/bin/bash

# Ensure task data files are available in /app/
# (they may have been generated to /opt/task_data/ during Docker build)
if [ -d /opt/task_data ] && [ ! -f /app/site_spec.json ]; then
    mkdir -p /app/output
    cp /opt/task_data/* /app/ 2>/dev/null || true
fi

pip3 install numpy==1.26.4 scipy==1.13.1 -q

python3 /solution/solver.py
