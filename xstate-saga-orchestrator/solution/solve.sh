#!/bin/bash


# Install npm dependencies
cd /app && npm install 2>&1 | tail -3

# Replace the broken saga.ts with the fixed version
cp /solution/saga_fixed.ts /app/src/saga.ts

echo "Applied fix to /app/src/saga.ts"
