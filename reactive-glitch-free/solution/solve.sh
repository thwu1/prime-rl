#!/usr/bin/env bash

set -u

cd /app

# Install dependencies
npm install 2>/dev/null

# Fix TypeScript config: NodeNext requires .js extensions in imports,
# but the project uses extensionless imports — switch to ESNext+bundler
cp /solution/tsconfig_fixed.json /app/tsconfig.json

# Fix build script: correct entry point, format, output path, target, platform
cp /solution/build_fixed.mjs /app/build.mjs

# Fix reactive core: implement push-pull scheduling with STALE/PENDING states,
# ownership trees, deferred batch execution, untrack, and onCleanup
cp /solution/reactive_fixed.ts /app/src/reactive.ts

# Fix store: implement signal-backed proxy reads with recursive nested wrapping,
# multi-level path setter, and batch-wrapped updater function
cp /solution/store_fixed.ts /app/src/store.ts

# Verify type-checking passes
npx tsc --noEmit

# Verify build produces correct output
node build.mjs
