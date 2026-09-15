#!/bin/bash

# Install dependencies
pip3 install mpmath==1.3.0 -q

# Generate verified improved implementations
python3 /solution/create_improved.py

# Run accuracy measurements and generate report
python3 /solution/run_measurement.py
