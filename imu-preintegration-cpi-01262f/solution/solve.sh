#!/bin/bash

set -e

# Install dependencies
pip3 install numpy==2.1.3

# Fix CMake and C++ source issues
python3 /solution/fix_build.py

# Build C++ ground truth generator
mkdir -p /app/build
cd /app/build
cmake /app/reference
make -j$(nproc)

# Generate ground truth
mkdir -p /app/output
./generate_groundtruth

# Copy Python implementation
cp /solution/cpi_preintegration.py /app/cpi_preintegration.py
cp /solution/process_imu.py /app/process_imu.py

# Run Python pipeline
cd /app
python3 process_imu.py
