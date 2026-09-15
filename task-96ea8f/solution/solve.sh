#!/bin/bash

# Wait for the API server to be ready
for i in $(seq 1 15); do
    if curl -s http://localhost:8080/api/tasks > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Run the pipeline solver (fetches from API, solves, submits, populates DB, generates PPM)
python3 /solution/pipeline.py

# Convert PPM visualizations to PNG using ImageMagick
cd /app/visualizations
for ppm in *.ppm; do
    [ -f "$ppm" ] || continue
    png="${ppm%.ppm}.png"
    convert "$ppm" "$png"
    rm "$ppm"
done

echo "Pipeline complete"
