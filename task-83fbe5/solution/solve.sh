#!/bin/bash

# Ensure data files are available
if [ ! -f /app/data/facilities.csv ]; then
    mkdir -p /app/data
    cp /opt/task_instance/*.csv /opt/task_instance/*.json /app/data/ 2>/dev/null
fi

pip3 install PuLP==2.9.0 -q
python3 /solution/solver.py
