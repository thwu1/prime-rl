#!/usr/bin/env bash

# Increase stack size to avoid potential stack overflow in recursive algorithms
ulimit -s unlimited 2>/dev/null || true

ENGINE_DIR="/app/engine"
ENGINE_BIN=""

# Check if already built (cmake or direct)
for p in "$ENGINE_DIR/build/CPPDubovSystem" "$ENGINE_DIR/CPPDubovSystem"; do
    if [ -f "$p" ]; then
        ENGINE_BIN="$p"
        break
    fi
done

if [ -z "$ENGINE_BIN" ]; then
    echo "Building engine with cmake..."
    cd "$ENGINE_DIR"
    mkdir -p build && cd build
    # Build WITHOUT Release optimizations to avoid UB-triggered crashes.
    # The engine's graph matching code can trigger UB under -O3 that causes SIGSEGV.
    if cmake .. 2>&1 && make -j"$(nproc)" 2>&1 && [ -f "$ENGINE_DIR/build/CPPDubovSystem" ]; then
        ENGINE_BIN="$ENGINE_DIR/build/CPPDubovSystem"
    else
        echo "CMake default build failed, trying with explicit Debug..."
        cd "$ENGINE_DIR"
        rm -rf build
        mkdir -p build && cd build
        if cmake .. -DCMAKE_BUILD_TYPE=Debug 2>&1 && make -j"$(nproc)" 2>&1 && [ -f "$ENGINE_DIR/build/CPPDubovSystem" ]; then
            ENGINE_BIN="$ENGINE_DIR/build/CPPDubovSystem"
        else
            echo "CMake builds failed, trying g++ directly..."
            cd "$ENGINE_DIR"
            g++ -std=c++20 -O0 -g -o CPPDubovSystem \
                DubovSystem/main.cpp \
                "DubovSystem/graph util/Graph.cpp" \
                "DubovSystem/graph util/BinaryHeap.cpp" \
                "DubovSystem/graph util/Matching.cpp" \
                "DubovSystem/csv util/csv.cpp" \
                DubovSystem/fpc.cpp \
                "DubovSystem/trf util/trf.cpp" \
                "DubovSystem/trf util/rtg.cpp" \
                DubovSystem/Player.cpp \
                DubovSystem/Tournament.cpp \
                DubovSystem/baku.cpp \
                DubovSystem/LinkedList.cpp \
                DubovSystem/explain.cpp \
                -I DubovSystem \
                -I "DubovSystem/graph util" \
                -I "DubovSystem/csv util" \
                -I "DubovSystem/trf util" 2>&1
            ENGINE_BIN="$ENGINE_DIR/CPPDubovSystem"
        fi
    fi
    cd /app
fi

if [ ! -f "$ENGINE_BIN" ]; then
    echo "ERROR: Failed to build engine"
    exit 1
fi

echo "Using engine: $ENGINE_BIN"

# Verify engine responds to --version
"$ENGINE_BIN" --version 2>/dev/null && echo "Engine verified." || echo "Engine version check skipped."

# Run the simulation
set -e
python3 /solution/simulator.py "$ENGINE_BIN"
