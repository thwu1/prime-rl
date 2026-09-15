#!/bin/bash


cd /app && npm install --silent 2>/dev/null

# Apply all bug fixes through code analysis and patching
python3 /solution/fix_bugs.py
