#!/bin/bash


pip3 install numpy==2.1.3 -q

# Copy solution files to /app
cp /solution/engine_impl.py /app/electrolyte_engine.py
cp /solution/makefile_content /app/Makefile
cp /solution/validate_results.py /app/validate_results.py

cd /app
make all
