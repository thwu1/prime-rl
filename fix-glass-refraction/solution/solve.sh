#!/bin/bash

pip3 install pyyaml==6.0.2 -q

# Extend rt.py with Cube, Cylinder, Group, CSG primitives
python3 /solution/extend_rt.py

# Install scene parser and renderer
cp /solution/scene_parser.py /app/scene_parser.py
cp /solution/render.py /app/render_scene.py

# Run the Makefile pipeline (render + verify with netpbm)
cd /app
make render
make verify
