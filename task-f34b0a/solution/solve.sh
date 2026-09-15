#!/bin/bash

# Fix CMakeLists.txt: correct C standard, add -lm, fix RPATH
cp /solution/CMakeLists_fixed.txt /app/CMakeLists.txt

# Replace buggy posit16.c with the correct implementation
cp /solution/posit16_correct.c /app/posit16.c

# Build with CMake
mkdir -p /app/build
cd /app/build
cmake ..
make
