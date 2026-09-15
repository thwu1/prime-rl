#!/usr/bin/env bash

set -euo pipefail

# Copy the implementation into place
cp /solution/cqf_impl.c /app/cqf.c

# Build the shared library
cd /app
make clean
make

# Verify the library was built
ls -la /app/libcqf.so

# Quick smoke test
pip3 install pytest==8.3.4 -q
python3 -m pytest /tests/test_state.py -v
