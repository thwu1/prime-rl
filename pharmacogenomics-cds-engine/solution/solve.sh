#!/usr/bin/env bash

cd /app

# Start PostgreSQL
pg_ctlcluster 16 main start 2>/dev/null || true
sleep 2

# Copy the engine
cp /solution/pgx_engine.py /app/pgx_engine.py

# Create the launcher script
cat > /app/pgx-cds << 'LAUNCHER'
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
from pgx_engine import main
main()
LAUNCHER

chmod +x /app/pgx-cds

# Initialize database and load reference data
/app/pgx-cds load-db
