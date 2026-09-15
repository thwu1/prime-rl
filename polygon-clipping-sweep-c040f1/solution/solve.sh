#!/bin/bash


set -e

cd /app
npm install --quiet 2>/dev/null

# Deploy the correct implementations of the three core modules
cp /solution/possible_intersection.ts /app/src/possible_intersection.ts
cp /solution/compute_fields.ts /app/src/compute_fields.ts
cp /solution/connect_edges.ts /app/src/connect_edges.ts

# Verify the implementation works by running a basic test
npx tsx -e "
import boolean from '/app/src/index';
const r = boolean([[[0,0],[4,0],[4,3],[0,3],[0,0]]], [[[2,0],[6,0],[6,3],[2,3],[2,0]]], 0);
if (!r || r.length === 0) { process.exit(1); }
console.log('Implementation verified: intersection produced', r.length, 'polygon(s)');
"
