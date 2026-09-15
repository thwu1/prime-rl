#!/usr/bin/env bash

pip3 install numpy==2.1.3 -q

# Compile C shared library
gcc -O2 -shared -fPIC -o /app/librotcore.so /solution/rotcore.c -lm

# Copy Python CLI
cp /solution/rotations.py /app/rotations.py
