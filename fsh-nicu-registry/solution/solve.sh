#!/bin/bash

# Install SUSHI
npm install -g fsh-sushi@3.16.5 2>/dev/null

# Generate all FSH files (fix broken ones, create missing ones)
python3 /solution/write_fsh.py

# Compile with SUSHI
cd /app
sushi .
