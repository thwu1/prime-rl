#!/bin/bash

# Copy solution source files to /app
cp /solution/assembler.c /app/assembler.c
cp /solution/CMakeLists.txt /app/CMakeLists.txt

# Build with cmake
cmake -B /app/build -S /app
cmake --build /app/build

# Create symlink so /app/assembler exists
ln -sf /app/build/assembler /app/assembler
