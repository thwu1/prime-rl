#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 psycopg2-binary==2.9.10 -q

# Configure trust authentication before starting PostgreSQL
cat > /etc/postgresql/16/main/pg_hba.conf << 'HBA'
local all all trust
host  all all 127.0.0.1/32 trust
host  all all ::1/128      trust
HBA

# Ensure socket directory exists with correct ownership
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql

# Start PostgreSQL (start or restart if already running)
pg_ctlcluster 16 main start 2>/dev/null || pg_ctlcluster 16 main restart 2>/dev/null || true

# Wait for PostgreSQL to accept connections
for i in $(seq 1 30); do
    pg_isready -U postgres -q && break
    sleep 1
done

# Recreate database from scratch
dropdb -U postgres --if-exists temporal_test 2>/dev/null || true
createdb -U postgres temporal_test
psql -U postgres -d temporal_test -f /app/seed.sql
psql -U postgres -d temporal_test -f /app/temporal.sql

# Run tests
RESULT=0
python3 -m pytest /tests/test_state.py -v --tb=short || RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
