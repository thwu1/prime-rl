#!/bin/bash

cd /app

# Evaluate all three parsers and produce reports
python3 /solution/evaluate.py

# Fix the best parser and build the conformant library
python3 /solution/fix_parser.py
make libconformant.so

# Run the pipeline with the conformant parser
python3 /app/pipeline.py --lib /app/libconformant.so
