#!/bin/bash

# Deploy APR calculator
cp /solution/apr_solver.py /app/regz_apr
chmod +x /app/regz_apr

# Deploy helper scripts
cp /solution/enrich.py /app/enrich.py
cp /solution/import_db.py /app/import_db.py
cp /solution/report.sh /app/report.sh
chmod +x /app/report.sh

# Deploy Makefile
cp /solution/pipeline.mk /app/Makefile

# Create schema.sql
cat > /app/schema.sql << 'SQL'
CREATE TABLE loan_results (
  id TEXT PRIMARY KEY,
  computed_apr REAL NOT NULL,
  transaction_type TEXT NOT NULL CHECK(transaction_type IN ('regular','irregular')),
  tolerance_pct REAL NOT NULL,
  disclosed_apr REAL,
  within_tolerance INTEGER,
  term_years INTEGER NOT NULL,
  apor_rate REAL NOT NULL,
  rate_spread REAL NOT NULL,
  high_cost INTEGER NOT NULL CHECK(high_cost IN (0,1))
);
SQL

# Create compliance_pipeline wrapper
cat > /app/compliance_pipeline << 'WRAPPER'
#!/bin/bash
make -C /app all >/dev/null 2>&1
cat /app/build/summary.json
WRAPPER
chmod +x /app/compliance_pipeline

mkdir -p /app/build
