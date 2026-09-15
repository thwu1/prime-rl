#!/bin/bash

cd /app

# Install dependencies
npm install --no-audit --no-fund 2>/dev/null

# Apply bug fixes via Python helper
python3 /solution/fix_bugs.py

# Copy model-based test file
cp /solution/ring-buffer.test.ts src/ring-buffer.test.ts

# Verify all tests pass
npx vitest run --reporter=verbose
