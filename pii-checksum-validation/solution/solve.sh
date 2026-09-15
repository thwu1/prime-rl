#!/bin/bash

set -e

# Fix recognizer bugs, implement anonymization, patch pipeline
python3 /solution/implement.py

# Run the complete pipeline
cd /app && python3 pipeline.py --seed 42
