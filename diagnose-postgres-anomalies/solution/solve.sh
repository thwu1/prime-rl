#!/bin/bash

# Ensure PostgreSQL is running
service postgresql start 2>/dev/null || pg_ctlcluster 16 main start 2>/dev/null || true
sleep 3

# Install solution dependencies
pip3 install psycopg2-binary==2.9.10 -q

# Capture baseline costs, diagnose, fix, and write report
python3 /solution/fix_database.py

# Restart PostgreSQL to apply settings that require restart (e.g. shared_buffers)
service postgresql restart 2>/dev/null || (pg_ctlcluster 16 main restart 2>/dev/null) || true
sleep 3

# Run post-restart performance evaluation
python3 /solution/post_eval.py

echo "All anomalies diagnosed, fixed, and evaluated. Reports at /app/diagnosis.json and /app/performance_eval.json"
