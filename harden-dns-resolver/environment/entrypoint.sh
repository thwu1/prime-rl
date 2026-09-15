#!/bin/bash
# Restore task files to /app if not already present
if [ ! -f /app/resolver.py ] && [ -f /opt/task/resolver.py ]; then
    cp /opt/task/resolver.py /app/resolver.py
fi
exec "$@"
