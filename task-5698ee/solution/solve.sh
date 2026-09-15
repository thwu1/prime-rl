#!/bin/bash

cd /app

# Install npm dependencies
npm install --silent 2>/dev/null

# Copy all fixed source files
cp /solution/encoder_fixed.ts /app/encoder.ts
cp /solution/hasher_fixed.ts /app/hasher.ts
cp /solution/eip712_fixed.ts /app/eip712.ts
