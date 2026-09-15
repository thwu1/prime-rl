#!/bin/bash

pip3 install numpy==2.1.3 -q

# Fix C source: correct num_blocks calculation, fix D-vector indexing, add causal variants
cp /solution/fixed_attention.c /app/src/blocked_attention.c
cp /solution/fixed_attention.h /app/src/blocked_attention.h

# Fix Makefile: output libattention.so (not blocked_attention.so) to match ctypes wrapper
cp /solution/fixed_makefile /app/Makefile

# Build the shared library
cd /app && make clean && make

# Install complete ctypes wrapper with causal bindings
cp /solution/fixed_wrapper.py /app/attention.py

# Install the final module that delegates to the C library
cp /solution/flash_attention_module.py /app/flash_attention.py
