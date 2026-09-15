#!/bin/bash


# Copy source and build system to /app
cp /solution/solver.cpp /app/solver.cpp
cp /solution/CMakeLists.txt /app/CMakeLists.txt

# Build with cmake
mkdir -p /app/build
cd /app/build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -- -j"$(nproc)"

# Install the binary
cp /app/build/solver /app/solver
chmod +x /app/solver

# Verify all puzzles
for puzzle in /app/puzzles/puzzle_*.xsb; do
    echo "=== Solving $(basename "$puzzle") ==="
    timeout 180 /app/solver "$puzzle"
    if [ $? -ne 0 ]; then
        echo "FAILED: $puzzle"
        exit 1
    fi
done
echo "=== All puzzles solved ==="
