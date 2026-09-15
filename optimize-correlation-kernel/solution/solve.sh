#!/bin/bash

# Install no extra deps needed - pure C++ solution

# Deploy optimized implementation
cp /solution/optimized_correlate.cpp /app/correlate.cpp
cp /solution/Makefile.opt /app/Makefile

# Build and run
cd /app && make clean && make && ./correlate
