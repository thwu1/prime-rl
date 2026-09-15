#!/bin/bash

# Copy modified C source with FairKalah support (captures parameter)
cp /solution/kalah_engine_fair.c /app/src/kalah_engine.c
cp /solution/kalah_engine_fair.h /app/src/kalah_engine.h

# Compile C library
cd /app && make

# Run solver
python3 /solution/solver.py
