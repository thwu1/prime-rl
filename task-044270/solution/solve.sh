#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Install complete solver implementation
cp /solution/frame3d_complete.py /app/frame3d.py

# Install complete Octave verification script
cp /solution/verify_kg_complete.m /app/octave_ref/verify_kg.m

# Run model processing pipeline
python3 /app/process_model.py /app/models/cantilever_circular.toml
