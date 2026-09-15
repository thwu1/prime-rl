#!/bin/bash

cd /app || exit 1
npm install --quiet 2>&1

# Ensure target directory exists
mkdir -p /app/src/types

# Deploy solution type implementations
cp /solution/is-matching.ts /app/src/types/IsMatching.ts
cp /solution/build-many.ts /app/src/types/BuildMany.ts
cp /solution/distribute-unions.ts /app/src/types/DistributeUnions.ts
cp /solution/deep-exclude.ts /app/src/types/DeepExclude.ts

# Verify solution compiles
cd /app && npx tsc --noEmit
echo "Solution verified: exit code $?"
