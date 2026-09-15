#!/bin/bash

# Deploy C++ solver source and build
cp /solution/solver.cpp /app/solver.cpp

# Build using the provided Makefile
make -C /app clean
make -C /app

# Run full evaluation pipeline (stores results in SQLite, outputs JSON)
bash /app/evaluate.sh | jq .
