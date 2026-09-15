#!/usr/bin/env bash

set -e
cd /app

# Fix CMakeLists.txt: correct source filenames, add missing source, fix target name
cat > CMakeLists.txt << 'CMAKEOF'
cmake_minimum_required(VERSION 3.10)
project(FloodRouting CXX)
set(CMAKE_CXX_STANDARD 17)
add_executable(flood_router
    src/main.cpp
    src/geometry.cpp
    src/routing.cpp
)
CMAKEOF

# Replace buggy source files with corrected implementations
cp /solution/geometry_fixed.cpp src/geometry.cpp
cp /solution/routing_fixed.cpp src/routing.cpp

# Build with cmake
cmake -B build
cmake --build build

# Run the simulation
./build/flood_router data/scenario.txt output.csv
