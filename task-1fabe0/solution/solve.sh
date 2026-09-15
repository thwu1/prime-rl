#!/bin/bash

# Evaluate and fix the bare-metal code, then design the overlay
python3 /solution/solution.py

# Build the complete project
cd /app
make clean && make

echo "Build complete: kernel8.img and hat-overlay.dtbo produced."
