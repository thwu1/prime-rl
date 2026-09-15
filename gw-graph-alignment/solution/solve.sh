#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.13.1 -q

# Apply all fixes to the pipeline (C code, Makefile, and Python)
python3 /solution/fix_pipeline.py

# Build the fixed native library
make -C /app/native/ clean
make -C /app/native/

# Run the pipeline to generate correct output
cd /app && python3 pipeline.py
