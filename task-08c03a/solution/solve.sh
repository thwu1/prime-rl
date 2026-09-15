#!/bin/bash

pip3 install PyYAML==6.0.2 -q

# Fix the three bugs in the existing pipeline
python3 /solution/fix_bugs.py

# Install the optimizer implementation
cp /solution/optimizer_impl.py /app/pipeline/optimizer.py

# Verify everything passes
python3 /app/validate.py
