#!/bin/bash

pip3 install numpy==2.1.3 -q

# Step 1: Fix the Makefile (add -lm for math library linkage) and compile
cd /app/gmpb_native
sed -i 's/LDFLAGS = -shared$/LDFLAGS = -shared -lm/' Makefile
make clean
make
cd /app

# Step 2: Install the complete ctypes wrapper
cp /solution/gmpb_wrapper.py /app/gmpb.py

# Step 3: Install the optimizer
cp /solution/optimizer_impl.py /app/optimizer.py

# Step 4: Run experiments (populates SQLite database + results.json)
python3 /solution/run_experiments.py
