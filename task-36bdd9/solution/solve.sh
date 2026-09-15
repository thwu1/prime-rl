#!/bin/bash

set -e

echo "=== Step 1: Build Ramulator 2.0 ==="
cd /app/ramulator2
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j"${BUILD_JOBS:-2}"
cp ./ramulator2 ../ramulator2
cd /app
echo "=== Build complete ==="

echo "=== Step 2: Install FCFS scheduler plugin ==="
cp /solution/fcfs_scheduler.cpp \
   /app/ramulator2/src/dram_controller/impl/scheduler/fcfs_scheduler.cpp

# Add FCFS scheduler to the CMake build system
if ! grep -q 'fcfs_scheduler' /app/ramulator2/src/dram_controller/CMakeLists.txt; then
    sed -i '/impl\/scheduler\/generic_scheduler.cpp/a\  impl/scheduler/fcfs_scheduler.cpp' \
        /app/ramulator2/src/dram_controller/CMakeLists.txt
fi
echo "=== FCFS scheduler installed ==="

echo "=== Step 3: Rebuild with FCFS scheduler ==="
cd /app/ramulator2/build
cmake ..
make -j"${BUILD_JOBS:-2}"
cp ./ramulator2 ../ramulator2
cd /app
echo "=== Rebuild complete ==="

echo "=== Step 4: Generate traces and configurations ==="
python3 /solution/setup_experiment.py

echo "=== Step 5: Run comparative simulations ==="
mkdir -p /app/sim_output
export LD_LIBRARY_PATH=/app/ramulator2:${LD_LIBRARY_PATH:-}

for config in frfcfs_sequential fcfs_sequential frfcfs_random fcfs_random; do
    echo "  Running ${config}..."
    /app/ramulator2/ramulator2 -f /app/configs/${config}.yaml \
        > /app/sim_output/${config}.txt 2>&1
    echo "  Done: ${config}"
done

echo "=== Step 6: Analyze results and evaluate ==="
python3 /solution/analyze_results.py

echo "=== All done ==="
