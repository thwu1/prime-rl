#!/bin/bash

cd /app

# Install dependencies
npm install 2>&1

# Copy fixed source files over the broken ones
cp /solution/fixed_types.ts /app/src/types.ts
cp /solution/fixed_stages.ts /app/src/stages.ts
cp /solution/fixed_compensation.ts /app/src/compensation.ts
cp /solution/fixed_pipeline.ts /app/src/pipeline.ts

# Verify TypeScript compilation
npx tsc --noEmit
echo "TypeScript compilation: exit code $?"

# Copy test runner for verification
cp /tests/test_runner.ts /app/test_runner.ts

# Verify all behavioral contracts
echo "=== Happy path ==="
npx tsx test_runner.ts happy

echo "=== Deploy failure path ==="
npx tsx test_runner.ts deploy_fail

echo "=== Test failure path ==="
npx tsx test_runner.ts test_fail
