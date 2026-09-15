#!/bin/bash

cd /app
npm install 2>/dev/null

# Apply all fixes to compose.ts
python3 /solution/apply_fix.py

# Compile the fixed TypeScript
npx tsc
