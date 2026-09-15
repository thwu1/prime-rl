#!/bin/bash

# No additional pip dependencies needed — uses only Python standard library

# Step 1: Start services for diagnosis
/app/start_services.sh 2>/dev/null || true
sleep 2

# Step 2: Fix collector.c (log buffering, size validation, resource leaks)
python3 /solution/fix_collector.py

# Step 3: Fix endpoint configuration (comment out the HTTP-speaking endpoint)
sed -i '/^svc-gamma/s/^/#/' /app/config/endpoints.conf

# Step 4: Recompile the collector
gcc -o /app/collector /app/collector.c

# Step 5: Generate post-incident analysis computationally
python3 /solution/write_postmortem.py

# Step 6: Create protocol health-check script
python3 /solution/write_healthcheck.py
chmod +x /app/healthcheck.sh
