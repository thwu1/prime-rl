#!/bin/bash

# Implement all missing functionality and fix bugs in mseed3pack.c
python3 /solution/implement.py

# Build and run
cd /app
make clean && make && ./mseed3pack
