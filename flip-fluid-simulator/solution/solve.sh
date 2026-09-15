#!/bin/bash

# Copy C source, Makefile, and Python wrapper to /app/
cp /solution/flip_core.c /app/flip_core.c
cp /solution/build.mk /app/Makefile
cp /solution/flip_wrapper.py /app/flip_sim.py

# Build the shared library
cd /app && make
