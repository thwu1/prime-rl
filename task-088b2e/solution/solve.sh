#!/bin/bash

# Fix the buggy template matching engine
python3 /solution/fix_matcher.py

# Install the conformance test execution engine
cp /solution/engine.py /app/engine.py

# Run the full pipeline
cd /app
make all
