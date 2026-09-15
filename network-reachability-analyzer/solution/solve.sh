#!/bin/bash

# Copy the solution engine into place and run it
cp /solution/engine_solution.py /app/engine.py
cd /app && python3 engine.py
