#!/bin/bash

set -e

cd /app

# Install dependencies
npm install --ignore-scripts 2>/dev/null

# Apply fixes to properties.ts and segmenter.ts
cp /solution/fixed_properties.ts /app/src/properties.ts
cp /solution/fixed_segmenter.ts /app/src/segmenter.ts

# Build
npx tsc

# Verify
node dist/cli.js test
