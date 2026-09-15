#!/bin/bash

cd /app
npm install --silent 2>/dev/null

# Apply the reactive system fix
python3 /solution/apply_fix.py
