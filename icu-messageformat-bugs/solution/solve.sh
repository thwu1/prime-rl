#!/bin/bash

cd /app
npm install --quiet 2>/dev/null

python3 /solution/fix_bugs.py
