#!/bin/bash

# Deploy the fixed proxy with per-destination port tracking and SO_REUSEADDR
cp /solution/fixed_proxy.py /app/proxy.py

# Remove stale results from any prior run
rm -f /app/proxy_results.json

echo "Fixed proxy deployed to /app/proxy.py"
