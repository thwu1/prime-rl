#!/usr/bin/env bash

# Copy solution files to /app/
cp /solution/spirv_parser.py /app/spirv_parser.py
cp /solution/dead_code_analyzer.py /app/dead_code_analyzer.py

# Run the dead code analyzer on all modules
cd /app
python3 /app/dead_code_analyzer.py
