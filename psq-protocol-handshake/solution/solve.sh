#!/bin/bash

cd /app

# Ensure inputs.json exists (fallback to backup location)
if [ ! -f /app/inputs.json ] && [ -f /data/inputs.json ]; then
    cp /data/inputs.json /app/inputs.json
fi

python3 /solution/psq_solve.py
