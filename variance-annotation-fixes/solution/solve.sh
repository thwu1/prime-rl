#!/bin/bash

cd /app

# Install TypeScript compiler
npm install -g typescript@5.4.5

# Apply all fixes via helper script
python3 /solution/fix_all.py

# Verify the fix compiles
tsc --noEmit --project /app/tsconfig.json
