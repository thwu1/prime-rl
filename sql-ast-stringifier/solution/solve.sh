#!/bin/bash

# Install Node.js dependencies
cd /app && npm install 2>&1

# Verify source files exist
ls /app/src/select.ts /app/src/func.ts /app/src/union.ts /app/src/init.ts || {
    echo "ERROR: Source files not found at /app/src/"
    exit 1
}

# Apply all nine bug fixes via computed string replacements
python3 /solution/apply_fixes.py
