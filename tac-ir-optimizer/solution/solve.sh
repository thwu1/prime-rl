#!/bin/bash

# Install the optimizer, Makefile, and report generator
cp /solution/optimizer.py /app/optimizer.py
cp /solution/Makefile /app/Makefile
cp /solution/gen_report.py /app/gen_report.py

# Run the full optimization pipeline
cd /app && make all
