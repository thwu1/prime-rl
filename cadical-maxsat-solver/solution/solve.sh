#!/bin/bash

set -e

# Build CaDiCaL from source
cd /app/cadical
./configure && make -j"$(nproc)"

# Compile the MaxSAT solver against CaDiCaL
g++ -O3 -o /app/maxsat \
    /solution/maxsat_solver.cpp \
    -I/app/cadical/src \
    /app/cadical/build/libcadical.a

chmod +x /app/maxsat
