#!/usr/bin/env bash

pip3 install pytest==8.3.4 -q 2>/dev/null

# Increase stack size
ulimit -s unlimited 2>/dev/null || true

# Find or build the engine
ENGINE_BIN=""
for p in /app/engine/build/CPPDubovSystem /app/engine/CPPDubovSystem; do
    if [ -f "$p" ]; then
        ENGINE_BIN="$p"
        break
    fi
done

if [ -z "$ENGINE_BIN" ]; then
    echo "Engine binary not found, building with cmake..."
    cd /app/engine
    mkdir -p build && cd build
    if cmake .. 2>&1 && make -j"$(nproc)" 2>&1 && [ -f /app/engine/build/CPPDubovSystem ]; then
        ENGINE_BIN="/app/engine/build/CPPDubovSystem"
    else
        echo "CMake build failed, trying g++..."
        cd /app/engine
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
        if [ -f /app/engine/CPPDubovSystem ]; then
            ENGINE_BIN="/app/engine/CPPDubovSystem"
        else
            echo "Engine build failed"
        fi
    fi
    cd /app
fi

export DUBOV_ENGINE_PATH="$ENGINE_BIN"
echo "Engine: $ENGINE_BIN"

pytest /tests/test_state.py -v --tb=short 2>&1
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
