#!/bin/bash


# Replace the broken analyzer with the fixed version
cp /solution/analyzer_fixed.ts /app/src/analyzer.ts

cd /app
npm install 2>/dev/null
npx tsc
node dist/analyzer.js target-project/tsconfig.json
