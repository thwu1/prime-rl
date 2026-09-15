#!/bin/bash

set -e

# Ensure build environment files are present at /app (restore from backup
# if the base image content was not properly overwritten during Docker build)
mkdir -p /app/include /app/src
for f in Makefile src/stress_test.cpp src/benchmark.cpp; do
    if [ -f "/opt/task_env/$f" ]; then
        cp -f "/opt/task_env/$f" "/app/$f"
    fi
done

# Generate the lock-free SPSC queue implementation
python3 /solution/generate_solution.py

# Build all targets
cd /app
make clean
make all

# Verify correctness
echo "=== Running stress test ==="
./build/stress_test 2000000

# Verify ThreadSanitizer cleanliness
echo "=== Running TSan stress test ==="
TSAN_OPTIONS=halt_on_error=1 ./build/stress_test_tsan 300000

# Verify performance
echo "=== Running benchmark ==="
./build/benchmark
