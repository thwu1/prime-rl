#!/bin/bash

# Copy reference analyzer into place
cp /solution/analyzer.py /app/analyzer.py

# Fix the Makefile
cp /solution/Makefile /app/Makefile

# Run the full pipeline
cd /app
make all
