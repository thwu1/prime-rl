#!/bin/bash

pip3 install sympy==1.13.3 mpmath==1.3.0 -q

# Compile the C CRC engine
make -C /app

# Run the analysis
python3 /solution/analyzer.py
