#!/bin/bash

# Extract MSS values from PCAP captures and deploy exploit
python3 /solution/solve_helper.py

# Validate
cd /app && python3 /app/validate.py
