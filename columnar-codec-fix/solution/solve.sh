#!/bin/bash

# Install TypeScript compiler
npm install -g typescript@5.5.4 2>/dev/null

cd /app

# Remove any extraneous .ts files the agent may have created outside the expected set
find /app/src -name '*.ts' \
  ! -name 'globals.d.ts' \
  ! -name 'leb128.ts' \
  ! -name 'rle.ts' \
  ! -name 'delta.ts' \
  ! -name 'boolean.ts' \
  ! -name 'columns.ts' \
  ! -name 'cli.ts' \
  -delete 2>/dev/null
find /app/src -mindepth 1 -type d -empty -delete 2>/dev/null

# Remove stale dist output
rm -rf /app/dist

# Apply fixes and complete implementations
python3 /solution/solve.py

# Compile TypeScript to JavaScript
tsc
