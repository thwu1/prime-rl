#!/bin/bash

# Copy solution implementation files
cp /solution/lattice_weight_complete.h /app/lattice_weight.h
cp /solution/lattice_proc_complete.cpp /app/lattice_proc.cpp
cp /solution/Makefile_reference /app/Makefile

# Build
cd /app && make
