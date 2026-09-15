#!/bin/bash
set -e


# Install dependencies
pip3 install numpy==2.1.3 Pillow==11.0.0 pytest==8.3.4 -q

# Apply all fixes and create adaptive detector
python3 /solution/solve_helper.py

# Run the pipeline
cd /app
make clean
make score
