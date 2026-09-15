#!/bin/bash

set -euo pipefail

# --- Generate the Isolation Breakthrough RBG file --------------------------
python3 /solution/generate_game.py

# --- Compile .rbg to C++ reasoner -----------------------------------------
echo "=== Compiling .rbg with rbg2cpp ==="
mkdir -p /tmp/sol_build
cd /tmp/sol_build
/app/rbg_system/rbg2cpp/bin/rbg2cpp -o reasoner /app/isolation_breakthrough.rbg

# --- Build the perft binary ------------------------------------------------
echo "=== Building perft binary ==="
CFLAGS="-O2 -std=c++20 -DRBG_RANDOM_GENERATOR=0 -DNDEBUG"
g++ -c -o /tmp/sol_build/reasoner.o /tmp/sol_build/reasoner.cpp $CFLAGS -I/tmp/sol_build
g++ -c -o /tmp/sol_build/perft.o /tests/perft.cpp $CFLAGS -I/tmp/sol_build
g++ -o /tmp/sol_build/perft /tmp/sol_build/reasoner.o /tmp/sol_build/perft.o $CFLAGS

# --- Verify with perft at depths 1-4 --------------------------------------
for d in 1 2 3 4; do
    echo ""
    echo "=== Perft Depth $d ==="
    /tmp/sol_build/perft "$d"
done
