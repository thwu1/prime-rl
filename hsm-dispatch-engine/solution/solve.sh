#!/bin/bash

# Ensure all app source files are present (fallback if Docker COPY failed)
if ! grep -q "TARGET = qhsmtst" /app/Makefile 2>/dev/null; then
    python3 /solution/setup_app.py
fi

# Generate the correct HSM engine implementation via computation
python3 /solution/generate_hsm.py

# Build and run
cd /app && make clean all && ./qhsmtst
