#!/bin/bash

set -u

# Ensure source files are present in /app
if [ ! -f /app/ntp_pipeline.c ]; then
    echo "Source files not found in /app/, restoring from backup..." >&2
    cp /opt/ntp_src/* /app/ 2>/dev/null || true
fi

# Verify files exist before proceeding
if [ ! -f /app/ntp_pipeline.c ]; then
    echo "FATAL: /app/ntp_pipeline.c still not found after restore attempt" >&2
    ls -la /app/ >&2
    ls -la /opt/ntp_src/ >&2
    exit 1
fi

# Apply all bug fixes via Python
python3 /solution/fix_all.py

# Rebuild
cd /app && make clean && make
