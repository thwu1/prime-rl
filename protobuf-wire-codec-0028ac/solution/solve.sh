#!/bin/bash

cd /app

# Apply all bug fixes via the helper script
python3 /solution/apply_fixes.py

# Build the corrected binary
go build -o pbcodec .
