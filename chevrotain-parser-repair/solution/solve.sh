#!/bin/bash

cd /app && npm install --no-audit --no-fund 2>/dev/null

python3 /solution/fix_bugs.py
