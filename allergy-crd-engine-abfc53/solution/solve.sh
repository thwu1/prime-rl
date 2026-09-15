#!/bin/bash


set -euo pipefail

cd /app

# Apply all fixes by writing complete corrected TypeScript files
python3 /solution/fix_all.py

# Install dependencies and compile
npm install --quiet 2>/dev/null
npx tsc
