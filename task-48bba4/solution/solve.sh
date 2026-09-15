#!/bin/bash

# Install solution dependencies
pip3 install qiskit==1.3.3 numpy==2.2.6 -q

# Run the corrected compilation pipeline
cd /app
python3 /solution/compile_pipeline.py
