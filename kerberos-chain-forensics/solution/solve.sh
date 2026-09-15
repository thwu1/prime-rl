#!/bin/bash

# Install solution dependencies
pip3 install pycryptodome==3.21.0 cryptography==44.0.0 pyyaml==6.0.2 -q

# Run the analysis
python3 /solution/analyze.py
