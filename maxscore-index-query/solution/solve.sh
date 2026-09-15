#!/bin/bash


# Compile trec_eval from source
make -C /app/tools/trec_eval

# Run the solver
python3 /solution/maxscore_solver.py
