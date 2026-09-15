#!/bin/bash

export PYTHONPATH=/app

# Deploy register allocator and code generator
cp /solution/regalloc_solution.py /app/regalloc.py
cp /solution/codegen_solution.py /app/codegen.py

# Validate Python-level correctness and native execution
cd /app
python3 /solution/validate.py
