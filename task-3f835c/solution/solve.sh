#!/bin/bash

cd /app

# Verify data files exist
for f in sysstat.lst system_event.lst db_cache_advice.lst librarycache.lst pgastat.lst pga_target_advice.lst sqlarea.lst; do
    if [ ! -f "/app/incident/$f" ]; then
        echo "ERROR: Required data file /app/incident/$f not found"
        ls -la /app/incident/ 2>/dev/null || echo "/app/incident/ directory does not exist"
        exit 1
    fi
done

if [ ! -f "/app/baselines/baselines.db" ]; then
    echo "ERROR: Baseline database not found at /app/baselines/baselines.db"
    exit 1
fi

python3 /solution/analyze.py
