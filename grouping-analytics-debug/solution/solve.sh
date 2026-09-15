#!/bin/bash

pip3 install psycopg2-binary==2.9.9 -q

pg_ctlcluster 16 main start 2>/dev/null || true
sleep 2

psql -U postgres -c "DROP DATABASE IF EXISTS analytics_db" 2>/dev/null || true
psql -U postgres -c "CREATE DATABASE analytics_db"
psql -U postgres -d analytics_db -f /app/setup.sql

python3 /solution/fix_analytics.py

psql -U postgres -d analytics_db -f /app/analytics.sql
