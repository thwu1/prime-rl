#!/bin/bash

# Fix 1: Replace catreactor.py with corrected version (fixes all Python bugs:
# bimolecular denom, arrhenius implementation, gas-phase equations, parallel
# mixing, recycle convergence, and adds DB lookup support)
cp /solution/catreactor.py /app/catreactor.py
chmod +x /app/catreactor.py

# Fix 2: Replace schema.sql (corrects swapped adsorption_K/heat_ads_kJ for B and D)
cp /solution/schema.sql /app/schema.sql

# Fix 3: Replace dbutil.py (fixes SQL column: heat_ads_kJ -> adsorption_K)
cp /solution/dbutil.py /app/reactor/dbutil.py

# Fix 4: Replace batch_run.sh (fixes jq filters: .cases[$i].input -> .cases[$i],
# .results -> .rate)
cp /solution/batch_run.sh /app/batch_run.sh
chmod +x /app/batch_run.sh

# Fix 5: Replace Makefile (fixes variable reference: BATCH_INPUT -> BATCH_IN)
cp /solution/Makefile /app/Makefile

# Initialize the database from the corrected schema
sqlite3 /app/properties.db < /app/schema.sql
