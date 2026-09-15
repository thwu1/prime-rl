#!/bin/bash

cp /solution/mbs_solution.py /app/mbs_analytics.py
cd /app
python3 /app/mbs_analytics.py \
  --freddie-orig /data/origination.txt \
  --freddie-perf /data/performance.txt \
  --ginniemae-factors /data/ginniemae_factors.dat \
  --psa-speed 150 \
  --projection-months 36

# Execute validation SQL via sqlite3 CLI
sqlite3 /app/output/mbs.db < /app/output/validate.sql
