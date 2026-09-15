#!/bin/bash
# Restore task data from /opt/taskdata/ to /app/ if missing
if [ ! -f /app/catalog.db ]; then
    mkdir -p /app/data
    cp /opt/taskdata/data/* /app/data/ 2>/dev/null
    cp /opt/taskdata/catalog.db /app/ 2>/dev/null
    cp /opt/taskdata/workload.txt /app/ 2>/dev/null
    cp /opt/taskdata/engine.py /app/ 2>/dev/null
    cp /opt/taskdata/README.md /app/ 2>/dev/null
fi
