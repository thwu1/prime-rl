#!/bin/bash

# Install scikit-bio (includes numpy, scipy, pandas as dependencies)
pip3 install scikit-bio==0.7.3 -q

# Run the analysis
python3 /solution/solve_analysis.py
