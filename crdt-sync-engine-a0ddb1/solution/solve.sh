#!/bin/bash

# Copy solution implementation files to /app/src/
cp /solution/types.ts /app/src/types.ts
cp /solution/encoding_impl.ts /app/src/encoding.ts
cp /solution/document_impl.ts /app/src/document.ts
cp /solution/update_impl.ts /app/src/update.ts
cp /solution/sync_impl.ts /app/src/sync.ts
cp /solution/cli_impl.ts /app/src/cli.ts

# Build
cd /app
npm install
npx tsc
