#!/bin/bash

cd /app
npm install --silent 2>/dev/null

# Copy corrected implementations
cp /solution/src/simulation.ts /app/src/simulation.ts
cp /solution/src/quadtree.ts /app/src/quadtree.ts
mkdir -p /app/src/forces
cp /solution/src/forces/manyBody.ts /app/src/forces/manyBody.ts
cp /solution/src/forces/collide.ts /app/src/forces/collide.ts
cp /solution/src/forces/link.ts /app/src/forces/link.ts

# Verify the fixes work
npx ts-node src/run.ts all
