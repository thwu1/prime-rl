#!/bin/bash

# Compile LLVM IR to PTX for matmul kernel
llc-18 --march=nvptx64 --mcpu=sm_80 -o /app/kernels/matmul.ptx /app/kernels/matmul.ll

# Deploy the solution analyzer
cp /solution/ptx_analyzer.py /app/ptx_analyzer.py
chmod +x /app/ptx_analyzer.py
