#!/bin/bash

# Install the implementation
cp /solution/solution.py /app/levenshtein_dfa.py

# Generate format spec via hex analysis and benchmark report via hyperfine
python3 /solution/write_artifacts.py
