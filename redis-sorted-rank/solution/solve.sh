#!/bin/bash

# Ensure original source files are in /app/ (copy from safe backup)
cp -a /opt/redis-src/. /app/

# Apply solution patches to the source code
python3 /solution/patch_source.py

# Build the server
cd /app && make clean && make
