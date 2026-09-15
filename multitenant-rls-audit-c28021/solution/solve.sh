#!/bin/bash


# Start PostgreSQL
service postgresql start 2>/dev/null || true
for i in $(seq 1 30); do
    if pg_isready -q 2>/dev/null; then break; fi
    sleep 1
done

# Apply security fixes
python3 /solution/fix_policies.py || exit 1

# Reinitialize the database with fixed policies
/app/setup.sh || true

echo "All security fixes applied and database reinitialized."
