#!/bin/bash


set -e

cd /app

# Install npm dependencies
npm install --ignore-scripts 2>/dev/null

# Deploy the correct implementations of the three core modules
# and the fix for the compare_segments bug
cp /solution/possible_intersection.ts /app/src/possible_intersection.ts
cp /solution/compute_fields.ts /app/src/compute_fields.ts
cp /solution/connect_edges.ts /app/src/connect_edges.ts
cp /solution/compare_segments.ts /app/src/compare_segments.ts

echo "Solution deployed: possible_intersection, compute_fields, connect_edges, compare_segments"
