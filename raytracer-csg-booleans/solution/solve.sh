#!/bin/bash

# Copy CSG implementation into the source tree
cp /solution/csg.h /app/src/csg.h

# Copy modified main with CSG demonstration scene
cp /solution/main_csg.cc /app/src/main.cc

# Build
cd /app
rm -rf build
mkdir -p build
cd build
cmake .. && make -j$(nproc)
