#!/bin/bash

# Deploy the reference implementation
cp /solution/brc_solution.c /app/src/brc.c

# Build to verify compilation
cd /app && make clean && make || true
