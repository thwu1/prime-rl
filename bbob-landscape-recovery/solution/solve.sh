#!/bin/bash

# Install solution dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 coco-experiment==2.8.2 -q

# Copy standalone implementation to /app
cp /solution/bbob_impl.py /app/bbob_impl.py

# Run the solver
python3 /solution/solver.py
