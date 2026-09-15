#!/bin/bash

pip3 install scipy==1.14.1 trimesh==4.4.3 -q

# Deploy fixed pipeline
cp /solution/cad_eval_fixed.py /app/cad_eval.py

# Run the pipeline
cd /app
python3 /app/cad_eval.py /app/manifest.json /app/results.json
