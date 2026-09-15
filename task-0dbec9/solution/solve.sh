#!/bin/bash

# Deploy the BSP engine
cp /solution/bsp_solver.py /app/bsp_engine
chmod +x /app/bsp_engine

# Process all maps
mkdir -p /app/results
for map in /app/maps/*.json; do
    name=$(basename "$map" .json)
    /app/bsp_engine "$map" "/app/results/${name}.json"
done
