#!/bin/bash

# Compile the C solver
make -C /app/tools

# Run the analysis pipeline
python3 /solution/solver.py
