#!/bin/bash

# Install dependencies
cd /app && npm install 2>&1 | tail -5

# Apply all fixes to the patch engine
python3 /solution/fix_engine.py
