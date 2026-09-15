#!/bin/bash

# Ensure task data is available at /app/
/usr/local/bin/init-app.sh 2>/dev/null || true

cd /app
python3 /solution/reference.py
