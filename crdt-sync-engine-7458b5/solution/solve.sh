#!/bin/bash

set -euo pipefail

cd /app

# Install dependencies
npm install --silent 2>/dev/null

# Replace the broken sync-engine.ts with the fixed version
cp /solution/sync-engine-fixed.ts /app/src/sync-engine.ts

# Recompile
npx tsc
