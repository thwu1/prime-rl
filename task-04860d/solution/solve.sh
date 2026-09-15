#!/bin/bash

set -e
export PIP_BREAK_SYSTEM_PACKAGES=1

python3 -m pip install numpy==2.1.3 -q
cp /solution/mesh_pipeline.py /app/mesh_pipeline.py
python3 /app/mesh_pipeline.py
