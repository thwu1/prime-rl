#!/bin/bash

# Copy solution files to /app
cp /solution/optimizer.py /app/optimizer.py
cp /solution/cfg_gen.py /app/cfg_gen.py
cp /solution/report_gen.py /app/report_gen.py
cp /solution/Makefile /app/Makefile

chmod +x /app/optimizer.py /app/cfg_gen.py /app/report_gen.py

# Run the full pipeline
cd /app
make all
