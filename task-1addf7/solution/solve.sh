#!/bin/bash

# Copy analyzer to /app and run it
cp /solution/ebpf_analyzer.py /app/ebpf_analyzer.py
cd /app
python3 /app/ebpf_analyzer.py
