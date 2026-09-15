#!/usr/bin/env bash

# Install solution dependencies
pip3 install cryptography==43.0.3 -q

# Run the session recovery and analysis solution
python3 /solution/solve.py
