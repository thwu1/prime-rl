#!/bin/bash

# Install solution dependencies
pip3 install numpy==1.26.4 -q

# Deploy the optimizer implementation
cp /solution/optimizer_impl.py /app/optimizer.py

echo "Optimizer installed at /app/optimizer.py"
