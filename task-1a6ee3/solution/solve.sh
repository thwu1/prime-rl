#!/bin/bash

# Copy the reference solution to /app
cp /solution/fingerprint_engine.py /app/fingerprint.py
chmod +x /app/fingerprint.py

# Run the fingerprinting engine
cd /app
python3 /app/fingerprint.py
