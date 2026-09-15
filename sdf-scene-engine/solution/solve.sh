#!/bin/bash

cd /app

# Evaluate scene queries
python3 /solution/engine.py /app/scene.json /app/queries.json /app/results.json

# Render depth map as PGM
python3 /solution/render.py /app/scene.json /app/camera.json /app/render.pgm

# Convert PGM to PNG
convert /app/render.pgm /app/render.png

# Generate cross-section data
python3 /solution/cross_section.py /app/scene.json /app/cross_section.dat

# Plot cross-section
gnuplot /solution/plot.gp
