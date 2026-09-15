#!/usr/bin/env bash


set -e

cd /app

# Write the complete compiler implementation
python3 /solution/write_compiler.py

# Build and run all tests to verify
make clean
make test
