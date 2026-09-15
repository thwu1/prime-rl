#!/bin/bash

# Install the transfer function implementation
cp /solution/impl.py /app/transfer_functions.py

# Generate verification report
python3 /solution/gen_report.py

# Run LLVM cross-validation
python3 /solution/cross_validate.py
