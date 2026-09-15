#!/bin/bash

set -e

cd /app

# Step 1: Install TypeScript compiler
echo "Installing dependencies..."
npm install 2>/dev/null

# Step 2: Analyze the JavaScript source and consumer TypeScript files,
#          then construct both declaration files from the analysis.
echo "Analyzing source code and building declarations..."
python3 /solution/build_declarations.py

# Step 3: Verify compilation
echo "Verifying with tsc --noEmit..."
npx tsc --noEmit
echo "Success: tsc --noEmit passed with no errors"
