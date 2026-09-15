#!/bin/bash

# Restore forensics data from backup if missing
if [ ! -f /app/forensics/memory.bin ]; then
    if [ -d /opt/forensics-backup ]; then
        mkdir -p /app/forensics
        cp -r /opt/forensics-backup/* /app/forensics/
    fi
fi

cd /app
python3 /solution/solver.py
