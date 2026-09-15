#!/bin/bash

cd /app

# Install dependencies
npm install --ignore-scripts 2>/dev/null

# Ensure directories exist
mkdir -p /app/grammar /app/src/generated

# Apply the corrected grammar
cp /solution/sql_fixed.pegjs /app/grammar/sql.pegjs

# Apply the corrected TypeScript files
cp /solution/stringify_fixed.ts /app/src/stringify.ts
cp /solution/transform_fixed.ts /app/src/transform.ts

# Generate parser from fixed grammar
npx peggy --format commonjs -o src/generated/parser.js grammar/sql.pegjs

# Compile TypeScript
npx tsc
