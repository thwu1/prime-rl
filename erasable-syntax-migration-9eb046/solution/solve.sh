#!/bin/bash

set -e

cd /app

# Install TypeScript compiler
npm install

# Replace all source files with refactored versions (erasable syntax only)
cp /solution/protocol.ts /app/src/protocol.ts
cp /solution/transport.ts /app/src/transport.ts
cp /solution/middleware.ts /app/src/middleware.ts
cp /solution/registry.ts /app/src/registry.ts
cp /solution/main.ts /app/src/main.ts

# Clean any stale compilation output
rm -rf /app/dist

# Compile using local tsc binary directly (avoids npx resolution issues)
./node_modules/.bin/tsc

# Verify output
node dist/main.js
