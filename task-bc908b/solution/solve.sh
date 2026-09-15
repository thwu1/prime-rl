#!/bin/bash

# Install solution dependencies
pip3 install requests==2.31.0 pyyaml==6.0.2 -q

# Deploy solution components
cp /solution/fault_analyzer.py /app/fault_analyzer.py

# Generate the executable runner script
python3 /solution/create_runner.py
