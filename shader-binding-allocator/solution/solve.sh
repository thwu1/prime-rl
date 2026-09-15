#!/bin/bash

# Copy the pipeline into place
cp /solution/pipeline.py /app/pipeline.py

# Verify it works on both shader files
python3 /app/pipeline.py /app/shaders/particles.glsl /tmp/particles_check
python3 /app/pipeline.py /app/shaders/scene.glsl /tmp/scene_check

echo "Pipeline installed and verified."
