#!/bin/bash

set -e

# Step 1: Build TCC from the mob branch source, including libtcc
cd /app/tcc-src
./configure --prefix=/app/tcc-inst
make -j"$(nproc)"
make install
cd /app

# Step 2: Deploy the fixed series evaluator source
cp /solution/series_jit.c /app/series_jit.c

# Step 3: Compile the evaluator, linking against the freshly-built libtcc
gcc -O2 -o /app/series_jit /app/series_jit.c \
    -I/app/tcc-inst/include \
    -L/app/tcc-inst/lib \
    -ltcc -ldl -lm -lpthread

# Step 4: Run the program to produce output.txt
/app/series_jit
