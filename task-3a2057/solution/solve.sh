#!/bin/bash

# Install solution dependencies
pip3 install mpmath==1.3.0 -q

# Generate all solution artifacts
python3 /solution/create_solution.py
