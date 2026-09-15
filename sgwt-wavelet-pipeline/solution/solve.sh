#!/usr/bin/env bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Apply all fixes (Makefile, C code, Python modules)
python3 /solution/fix_pipeline.py

# Compile the C shared library
cd /app && make

# Run the pipeline
python3 /app/run_sgwt.py
