#!/bin/bash

cd /app

# Run the optimizer to produce results.json, kernel_plan.json, and blas_eval.c
python3 /solution/solve.py

# Compile the CBLAS evaluation program
gcc -o /app/blas_eval /app/blas_eval.c -lopenblas -lm
echo "CBLAS evaluation compiled successfully"

# Run it to verify
/app/blas_eval
