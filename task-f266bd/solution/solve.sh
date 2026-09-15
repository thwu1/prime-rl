#!/bin/bash

cd /app

# Extract diagnostic bundle
mkdir -p /app/diagnostics
tar xzf /app/diagnostics.tar.gz -C /app/

# Deploy and run recovery implementation
cp /solution/recovery.py /app/recovery.py
python3 /app/recovery.py
