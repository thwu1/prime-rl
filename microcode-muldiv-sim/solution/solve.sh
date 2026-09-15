#!/bin/bash

cd /app

# Copy all solution files
cp /solution/simulator.py /app/simulator.py
cp /solution/corx.v /app/corx.v
cp /solution/corx_tb.v /app/corx_tb.v
cp /solution/parse_vcd.py /app/parse_vcd.py
cp /solution/orchestrate.py /app/orchestrate.py

# Run the full pipeline: Python sim + Verilog compile/sim + VCD parse
python3 /app/orchestrate.py
