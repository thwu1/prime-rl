#!/bin/bash

# --- PostgreSQL Setup ---
service postgresql start
for i in $(seq 1 30); do
    pg_isready -h 127.0.0.1 -q 2>/dev/null && break
    sleep 1
done

psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE cds_audit;" 2>/dev/null
psql -h 127.0.0.1 -U postgres -d cds_audit -c "
CREATE TABLE IF NOT EXISTS decision_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    patient_id TEXT NOT NULL,
    hook_instance TEXT NOT NULL,
    cards_count INTEGER NOT NULL,
    max_severity TEXT NOT NULL,
    request_hash TEXT NOT NULL
);
"

# --- Deploy corrected application code ---
cp /solution/server.py /app/server.py
cp /solution/interaction_engine.py /app/interaction_engine.py

# --- Deploy corrected nginx configuration ---
cp /solution/nginx_cds.conf /etc/nginx/sites-enabled/cds-proxy
nginx -t && service nginx restart
