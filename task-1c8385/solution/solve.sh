#!/bin/bash

# Copy complete C implementation over the stub
cp /solution/bf16_impl.c /app/bf16.c

# Fix the Makefile: add -fPIC, -shared, and -lm
cp /solution/Makefile.fixed /app/Makefile

# Copy complete Python ctypes wrapper
cp /solution/bf16_wrapper.py /app/bf16.py

# Build the shared library
cd /app && make
