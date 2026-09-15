#!/usr/bin/env bash

set -euo pipefail

cd /app

# Verify source files exist before running transforms
echo "Checking source files..."
for f in pricing checkout dashboard analytics api notifications settings reports; do
  if [ ! -f "/app/src/${f}.js" ]; then
    echo "ERROR: /app/src/${f}.js not found"
    ls -la /app/src/
    exit 1
  fi
done
echo "All 8 source files present."

# Copy the composed codemod pipeline into the project's codemods directory
cp /solution/pipeline.js /app/codemods/pipeline.js

# Dynamically discover all top-level JS files in src/ (excludes utils/ subdirectory)
# This avoids hardcoding paths that jscodeshift might report as non-existent
SRC_FILES=$(find /app/src -maxdepth 1 -name '*.js' -type f | sort)
echo "Files to transform:"
echo "$SRC_FILES"

# Run jscodeshift with the pipeline against discovered source files
npx jscodeshift \
  --parser=babel \
  --run-in-band \
  --no-babel \
  -t /app/codemods/pipeline.js \
  $SRC_FILES

echo "Codemod pipeline applied successfully."
