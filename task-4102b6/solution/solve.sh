#!/bin/bash

pip3 install scapy==2.6.1 -q

cd /app

# Write the Scapy layer implementation
python3 /solution/write_layers.py

# Run the analysis
python3 /app/analyze.py
