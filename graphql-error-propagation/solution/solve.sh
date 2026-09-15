#!/usr/bin/env bash

set -euo pipefail

# Install Node.js dependencies
cd /app && npm install --save-dev tsx@4.19.4 typescript@5.7.3 2>&1 | tail -1

# Replace the broken engine with the corrected implementation
cp /solution/engine_fixed.ts /app/src/engine.ts

echo "Solution applied successfully."
