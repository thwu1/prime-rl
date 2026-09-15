#!/bin/bash

# Fix all pipeline bugs (Makefile, C code, ctypes bridge, Python library)
python3 /solution/fix_all.py

# Build the C shared library
cd /app && make clean && make

# Run benchmarks to generate /app/results.json
cd /app && python3 run_benchmarks.py

# Run the evaluation framework to generate /app/evaluation.json
python3 /solution/implement_eval.py
