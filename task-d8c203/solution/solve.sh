#!/bin/bash

# Start PostgreSQL
pg_ctlcluster 16 main start 2>/dev/null || true
pg_isready -U postgres -t 30

# Fix the function: apply corrected implementation
psql -U postgres -d postgres_air -f /solution/fixed_function.sql

# Fix the index infrastructure:
# Drop the decoy index on raw email (useless for lower(email) queries)
psql -U postgres -d postgres_air -c "DROP INDEX IF EXISTS postgres_air.idx_booking_email;"

# Drop the hash index on lower(email) (hash cannot support LIKE prefix matching)
psql -U postgres -d postgres_air -c "DROP INDEX IF EXISTS postgres_air.idx_booking_email_lower;"

# Create the correct index: btree with text_pattern_ops on the lower() expression
psql -U postgres -d postgres_air -c "CREATE INDEX idx_booking_email_lower ON postgres_air.booking (lower(email) text_pattern_ops);"

# Update statistics after index changes
psql -U postgres -d postgres_air -c "ANALYZE postgres_air.booking;"

echo "All fixes applied."
