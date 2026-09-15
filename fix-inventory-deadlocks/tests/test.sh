#!/bin/bash

set -u

pip3 install pytest==8.3.4 psycopg2-binary==2.9.10 -q

# Fix /etc/passwd and /etc/group permissions so all users can resolve UIDs
# (containers sometimes restrict these, breaking psql/libpq user lookup)
chmod a+r /etc/passwd /etc/group 2>/dev/null || true

# Identify PostgreSQL version
PG_VERSION=$(ls /etc/postgresql/ | sort -V | tail -1)

# Configure trust authentication for both Unix socket and TCP connections
PG_HBA="/etc/postgresql/${PG_VERSION}/main/pg_hba.conf"
printf 'local all all trust\nhost all all 127.0.0.1/32 trust\nhost all all ::1/128 trust\n' > "$PG_HBA"

# Ensure PostgreSQL socket directory exists with correct ownership
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql
chmod 2775 /var/run/postgresql

# Start PostgreSQL
pg_ctlcluster "$PG_VERSION" main start 2>&1 || true

# Wait for PostgreSQL to accept connections (up to 30 seconds)
for _i in $(seq 1 30); do
    pg_isready -h 127.0.0.1 -U postgres -q 2>/dev/null && break
    sleep 1
done

# Create test database (use TCP via -h to avoid Unix socket UID lookup issues)
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE inventory_test;" 2>/dev/null || true

# Load schema (always from the original, unmodified file)
psql -U postgres -h 127.0.0.1 -d inventory_test -f /app/schema.sql -q

# Load the solver's procedures
psql -U postgres -h 127.0.0.1 -d inventory_test -f /app/procedures.sql -q

# Load any additional SQL files the solver may have created
for f in /app/*.sql; do
    base=$(basename "$f")
    if [ "$base" != "schema.sql" ] && [ "$base" != "procedures.sql" ]; then
        psql -U postgres -h 127.0.0.1 -d inventory_test -f "$f" -q 2>/dev/null || true
    fi
done

# Lower deadlock_timeout for faster deadlock detection in tests
psql -U postgres -h 127.0.0.1 -d inventory_test -c "ALTER SYSTEM SET deadlock_timeout = '200ms';" -q
psql -U postgres -h 127.0.0.1 -d inventory_test -c "SELECT pg_reload_conf();" -q

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
