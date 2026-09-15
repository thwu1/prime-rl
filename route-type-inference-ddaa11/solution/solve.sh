#!/bin/bash

cd /app

# Install dependencies
npm install --silent 2>/dev/null

# Apply fixes via computational patching
python3 /solution/fix_code.py

# Verify
npx tsc --noEmit && npx vitest run
