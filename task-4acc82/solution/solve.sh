#!/bin/bash

# Fix both broken components and produce correct output
python3 /solution/solve_helper.py

# Run the corrected pipeline to produce results.csv
bash /app/pipeline.sh
