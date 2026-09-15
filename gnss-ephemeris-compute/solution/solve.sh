#!/bin/bash

cd /app

cp /solution/gnss_solver.py /app/gnss_pipeline.py

python3 /app/gnss_pipeline.py process \
  --nav /app/data/mixed.25n /app/data/gps_v2.99n \
  --db /app/output/gnss.db \
  --report /app/output/report.json

python3 /app/gnss_pipeline.py convert \
  --input /app/data/gps_v2.99n \
  --output /app/output/converted.25n

python3 /app/gnss_pipeline.py export \
  --db /app/output/gnss.db \
  --sp3 /app/output/orbits.sp3

python3 /app/gnss_pipeline.py validate \
  --db /app/output/gnss.db \
  --sp3 /app/output/orbits.sp3 \
  --output /app/output/validation.json
