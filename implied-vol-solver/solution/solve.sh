#!/bin/bash

# Copy solution source files to /app
mkdir -p /app/src
cp /solution/ivol.c /app/src/ivol.c
cp /solution/ivol.h /app/src/ivol.h
cp /solution/Makefile /app/Makefile
cp /solution/iv_solver.py /app/iv_solver.py

# Build the shared library
make -C /app
