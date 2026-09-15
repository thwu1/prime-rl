#!/usr/bin/env bash

# Run the complete solution pipeline:
# 1. Fix C library bugs and Makefile
# 2. Compile the shared library
# 3. Run the Python estimator (uses ctypes + SQLite)
python3 /solution/estimator.py
