#!/bin/bash

set -e

cd /app

# Generate the PAC from the SVD
python3 /solution/generate_pac.py

# Build for ARM target
cargo build --target thumbv7m-none-eabi
echo "PAC built successfully for thumbv7m-none-eabi"
