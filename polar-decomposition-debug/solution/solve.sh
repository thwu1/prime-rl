#!/bin/bash

pip3 install numpy==2.1.3 -q

# Fix bugs in the library and implement missing functionality
python3 /solution/fix_code.py

# Run stability evaluations and populate the database
python3 /solution/evaluate.py

# Generate convergence analysis comparing coefficient sets
python3 /solution/convergence.py
