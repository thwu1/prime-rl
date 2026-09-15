#!/bin/bash


# Install solution dependencies
pip3 install libcst==1.5.1 -q 2>/dev/null

# Generate the complete transformer implementation
python3 /solution/write_transformer.py
