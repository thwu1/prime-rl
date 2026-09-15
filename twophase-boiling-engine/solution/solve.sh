#!/bin/bash

# Install dependencies (ht pulls in fluids, numpy, scipy)
pip3 install ht==1.2.0 -q

# Deploy the solution
cp /solution/twophase_impl.py /app/twophase.py

# Run to generate results
python3 /app/twophase.py
