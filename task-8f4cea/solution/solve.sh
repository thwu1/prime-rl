#!/bin/bash

# Start PostgreSQL if not running
pg_isready -U postgres -q 2>/dev/null || {
    PG_VER=$(ls /etc/postgresql/ | head -1)
    pg_ctlcluster "$PG_VER" main start
}
until pg_isready -U postgres -q; do sleep 0.5; done

# Apply index definitions
psql -U postgres -d eventdb -f /solution/indexes.sql

# Apply retention function
psql -U postgres -d eventdb -f /solution/retention.sql

# Update statistics after index creation
psql -U postgres -d eventdb -c "ANALYZE app.events;"
