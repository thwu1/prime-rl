#!/bin/bash

pip3 install z3-solver==4.12.6.0 -q

# Install the reference synthesizer and run it
cp /solution/solver.py /app/synthesize.py
cd /app && python3 synthesize.py all
