#!/bin/bash


# Install dependencies
pip3 install spiceypy==6.0.0 numpy==1.26.4 -q

# Run solution
cd /app
python3 /solution/solve.py
