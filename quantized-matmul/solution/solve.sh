#!/bin/bash

# Deploy the correct implementation with adaptive_quantized_matmul
cp /solution/qmatmul_solution.c /app/src/qmatmul.c

# Build the shared library
cd /app && make clean all
