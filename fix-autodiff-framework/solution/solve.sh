#!/bin/bash

cd /app

pip3 install numpy==2.1.3 -q

# Apply all fixes: Makefile, toposort, VJPs, wrapper path
python3 /solution/fix_autograd.py

# Build the C shared library
make -C /app/autograd/csrc/
