#!/bin/bash

# Solve the dual-firmware cryptographic audit challenge
cd /app && python3 /solution/solve_firmware.py

# Deploy the V3 key wrapping module
cp /solution/v3_keywrap.py /app/v3_keywrap.py
