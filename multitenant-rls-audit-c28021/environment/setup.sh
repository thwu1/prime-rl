#!/bin/bash
set -e

# Start PostgreSQL if not running
service postgresql start 2>/dev/null || true
sleep 2

# Wait for PostgreSQL to be ready
for i in $(seq 1 30); do
    if pg_isready -q 2>/dev/null; then
        break
    fi
    sleep 1
done

# Create database (drop if exists)
psql -U postgres -c "DROP DATABASE IF EXISTS multitenant;" 2>/dev/null || true
psql -U postgres -c "CREATE DATABASE multitenant;"

# Load schema and policies
psql -U postgres -d multitenant -f /app/schema.sql
psql -U postgres -d multitenant -f /app/policies.sql

echo "Database 'multitenant' initialized successfully."
echo "Connect with: psql -U postgres -d multitenant"
