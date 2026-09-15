#!/bin/bash

set -euo pipefail

# Start PostgreSQL
pg_ctlcluster 16 main start
sleep 3

# Diagnose and resolve orphaned prepared transaction
psql -U postgres -c "SELECT gid, prepared, owner, database FROM pg_prepared_xacts;"
psql -U postgres -c "ROLLBACK PREPARED 'failed_migration_20240115';"

# Re-enable autovacuum on audit_log (was disabled during a bulk load and never re-enabled)
psql -U postgres -c "ALTER TABLE audit_log SET (autovacuum_enabled = true);"

# Set per-table autovacuum scale factors — default 0.2 is far too high
# for tables with hundreds of thousands of rows
psql -U postgres -c "ALTER TABLE orders SET (autovacuum_vacuum_scale_factor = 0.01, autovacuum_vacuum_threshold = 1000);"
psql -U postgres -c "ALTER TABLE order_items SET (autovacuum_vacuum_scale_factor = 0.005, autovacuum_vacuum_threshold = 1000);"
psql -U postgres -c "ALTER TABLE audit_log SET (autovacuum_vacuum_scale_factor = 0.02, autovacuum_vacuum_threshold = 500);"

# Fix pathological global vacuum configuration
# cost_delay=50ms and cost_limit=50 throttle vacuum far too aggressively
psql -U postgres -c "ALTER SYSTEM SET autovacuum_vacuum_cost_delay = '2ms';"
psql -U postgres -c "ALTER SYSTEM SET autovacuum_vacuum_cost_limit = 800;"
# maintenance_work_mem=32MB causes excessive index vacuum cycles
psql -U postgres -c "ALTER SYSTEM SET maintenance_work_mem = '512MB';"
# Protective timeout to prevent future idle-in-transaction vacuum blocking
psql -U postgres -c "ALTER SYSTEM SET idle_in_transaction_session_timeout = '300000';"

# Reload configuration
psql -U postgres -c "SELECT pg_reload_conf();"

# Clear accumulated dead tuples
psql -U postgres -c "VACUUM VERBOSE orders;"
psql -U postgres -c "VACUUM VERBOSE order_items;"
psql -U postgres -c "VACUUM VERBOSE audit_log;"

# Create the vacuum health monitoring function
psql -U postgres -f /solution/health_function.sql

# Write global configuration documentation
cat > /app/postgresql_tuning.conf << 'CONF'
autovacuum_vacuum_cost_delay = 2ms
autovacuum_vacuum_cost_limit = 800
maintenance_work_mem = 512MB
idle_in_transaction_session_timeout = 300000
CONF

# Verify remediation via the health function
psql -U postgres -c "SELECT * FROM vacuum_health_report();"
