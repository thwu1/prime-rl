#!/bin/bash

set -e

# Fix TypeScript build configuration
cp /solution/tsconfig.json /app/tsconfig.json

# Fix source files
cp /solution/parser.ts /app/src/parser.ts
cp /solution/formatter.ts /app/src/formatter.ts
cp /solution/plural-rules.ts /app/src/plural-rules.ts

# Build
cd /app
npm install
npx tsc
