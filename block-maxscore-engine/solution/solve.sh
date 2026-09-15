#!/bin/bash

# Compile the C scoring library
cp /solution/scorer.c /app/scorer.c
gcc -O2 -shared -fPIC -o /app/libscorer.so /app/scorer.c -lm

# Install the Python search engine implementation
cp /solution/search_impl.py /app/search_engine.py

# Build and persist the index via CLI
cd /app && python3 /app/search_engine.py build
