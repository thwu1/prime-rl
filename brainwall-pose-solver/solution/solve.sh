#!/bin/bash

cd /app

# Extract test data from archive
make extract

# Install C source for binary format decoders
cp /solution/mdl2json.c /app/src/mdl2json.c
cp /solution/nbt2json.c /app/src/nbt2json.c

# Compile the C tools via Makefile
make tools

# Install simulation engine and pipeline entry point
cp /solution/simulate.py /app/simulator/simulate.py
cp /solution/run_sim.sh /app/simulator/run.sh
chmod +x /app/simulator/run.sh
