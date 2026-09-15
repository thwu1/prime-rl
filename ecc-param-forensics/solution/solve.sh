#!/bin/bash

# Compile the C reference tool for Montgomery parameter cross-validation
gcc -o /app/tools/monty_check /app/tools/monty_check.c -lcrypto 2>/dev/null

# Run the solver
python3 /solution/solver.py
