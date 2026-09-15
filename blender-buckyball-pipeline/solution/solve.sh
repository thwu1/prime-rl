#!/bin/bash

# Deploy the solution pipeline and execute it
cp /solution/conway_pipeline.py /app/conway_pipeline.py

xvfb-run -a blender --background --python /app/conway_pipeline.py
