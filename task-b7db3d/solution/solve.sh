#!/bin/bash

pip3 install numpy==2.1.3 -q

# Apply all fixes and complete all implementations
python3 /solution/fix_pipeline.py

# Run the pipeline
cd /app && python3 pipeline.py
