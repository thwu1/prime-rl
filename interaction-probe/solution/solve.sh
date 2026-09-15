#!/bin/bash

# Ensure Playwright browser binary is present (no-op if already installed, no apt needed)
python3 -m playwright install chromium 2>&1 | tail -1

# Copy reference probe and run it
cp /solution/solve_probe.py /app/probe.py
cd /app
python3 probe.py
