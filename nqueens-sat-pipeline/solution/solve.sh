#!/bin/bash

# Copy fixed implementations to /app/
cp /solution/generator.py /app/generator.py
cp /solution/encoder.py /app/encoder.py
cp /solution/solver.py /app/solver.py
cp /solution/counter.py /app/counter.py
cp /solution/phase_transition.py /app/phase_transition.py

# Run phase transition analysis
cd /app
python3 /app/phase_transition.py
