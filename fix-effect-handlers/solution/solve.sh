#!/bin/bash

# Copy the compiler and compile-all script into the app directory
cp /solution/effekt_to_scheme.py /app/effekt_to_scheme.py
cp /solution/compile_all.py /app/compile_all.py

echo "Installed effekt_to_scheme.py and compile_all.py to /app/"

# Validate by running compile_all.py
python3 /app/compile_all.py
