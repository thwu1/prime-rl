#!/bin/bash

pg_ctlcluster 16 main start 2>/dev/null || true
sleep 1

pip3 install psycopg2-binary==2.9.9 -q

cd /app
python3 /solution/analyze_ledger.py
