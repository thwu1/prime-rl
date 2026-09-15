#!/usr/bin/env bash
set -e

# Copy solution files into /app
cp /solution/incircle.h /app/incircle.h
cp /solution/verify_mpfr.cpp /app/verify_mpfr.cpp
cp /solution/CMakeLists.txt /app/CMakeLists.txt

# Build both targets
cmake -B /app/build -S /app
cmake --build /app/build

# Run tests to verify
/app/build/test_incircle
/app/build/verify_mpfr
