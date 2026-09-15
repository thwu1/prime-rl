#!/bin/bash

# Install solution dependencies
pip3 install r2pipe==1.9.4 -q

# Run the solve helper which uses radare2 to reverse engineer and build tooling
python3 /solution/solve_helper.py
