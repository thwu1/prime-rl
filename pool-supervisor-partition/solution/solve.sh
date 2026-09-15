#!/usr/bin/env bash

# Apply all fixes: partitioned supervisor, config, diagnostic script
cp /solution/fix_supervisor.py /app/supervisor.py
cp /solution/fix_config.toml /app/config.toml
cp /solution/fix_diagnose.sh /app/diagnose.sh
chmod +x /app/diagnose.sh

# Verify the fix
python3 /app/benchmark.py
