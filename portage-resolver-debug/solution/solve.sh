#!/usr/bin/env bash

# Restore source if needed
if [ ! -f /app/resolver/version.py ]; then
    mkdir -p /app/resolver
    cp -r /opt/task_src/* /app/
fi

cd /app
python3 /solution/fix_resolver.py
