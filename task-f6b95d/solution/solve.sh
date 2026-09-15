#!/bin/bash

# Ensure app source files are present (restore from staging if needed)
if [ ! -f /app/mapops.py ]; then
    cp -a /task_setup/. /app/ 2>/dev/null || true
fi

cd /app
python3 /solution/fix_all.py
