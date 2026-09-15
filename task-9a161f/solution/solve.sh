#!/bin/bash

# Build the verification tool
cd /app/tools && make -s undead-tool
cd /app

# Install solution files
cp /solution/solver.py /app/solver.py
cp /solution/generator.py /app/generator.py
cp /solution/validate.sh /app/validate.sh
chmod +x /app/validate.sh

# Run the full pipeline
bash /app/validate.sh
