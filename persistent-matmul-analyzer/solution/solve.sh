#!/bin/bash

# Fix all bugs across the modules
python3 /solution/fix_bugs.py

# Generate corrected predictions
python3 /app/predict.py
