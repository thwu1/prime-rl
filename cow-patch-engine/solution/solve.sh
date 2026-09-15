#!/usr/bin/env bash

set -e

# Copy solution files into the project
cp /solution/engine.ts /app/src/engine.ts
cp /solution/patches.ts /app/src/patches.ts

# Install dependencies and compile
cd /app
npm install
npx tsc
