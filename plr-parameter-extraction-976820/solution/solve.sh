#!/bin/bash


# Install solution dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Copy solution script to /app
cp /solution/solution.py /app/plr_analyze.py

echo "Solution installed."
