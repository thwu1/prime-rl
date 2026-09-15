#!/bin/bash

# Ensure directory structure exists
mkdir -p /app/src

# Apply all fixes and implement stubs
python3 /solution/fix_codec.py

# Install npm dependencies for tsx runtime
cd /app && npm install --silent 2>/dev/null
