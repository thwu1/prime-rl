#!/bin/bash

cd /app

# Install dependencies
npm install

# Apply all bug fixes and implement conditional branching
python3 /solution/fix_bugs.py

# Verify the fix compiles
npx tsc --noEmit
echo "tsc exit code: $?"
