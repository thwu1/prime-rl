#!/bin/bash

# Fix CMake build system issues

# Fix 1: Change PRIVATE to PUBLIC so include dirs propagate to linked targets
sed -i 's/target_include_directories(manipulator_core PRIVATE/target_include_directories(manipulator_core PUBLIC/' /app/CMakeLists.txt

# Fix 2: Remove the explicit PIC OFF that prevents shared library compilation on x86_64
sed -i '/POSITION_INDEPENDENT_CODE OFF/d' /app/CMakeLists.txt

# Install the correct IK implementation
cp /solution/ik_impl.cpp /app/src/ik.cpp

# Build with CMake
cd /app
cmake -B build
cmake --build build

# Verify round-trip IK correctness
./build/manipulator --verify 1000
