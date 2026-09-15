#!/bin/bash

cd /app

# Extract data from SQLite database to flat format
python3 /solution/extract_data.py

# Compile and run solver
g++ -O2 -std=c++17 -o /solution/solver /solution/solution.cpp
/solution/solver < /solution/input.txt > /app/output.txt
