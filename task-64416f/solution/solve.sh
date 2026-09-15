#!/bin/bash

# Install optimizer with --dot CFG support
cp /solution/optimizer.py /app/optimize.py
chmod +x /app/optimize.py

# Install completed Makefile
cp /solution/Makefile /app/Makefile

# Run the full pipeline to verify everything works
cd /app && make clean && make all
