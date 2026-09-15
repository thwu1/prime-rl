#!/bin/bash

cd /app

# Write the complete implementation
python3 /solution/implement_buffer.py
if [ $? -ne 0 ]; then
    echo "ERROR: implement_buffer.py failed"
    exit 1
fi

# Build and verify
cmake -B build -DCMAKE_BUILD_TYPE=Release 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: cmake configure failed"
    exit 1
fi

cmake --build build -- -j2 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: cmake build failed"
    exit 1
fi

./build/test_bipartite
