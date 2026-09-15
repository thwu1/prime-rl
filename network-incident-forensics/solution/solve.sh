#!/usr/bin/env bash

# Solution uses tshark (already in environment) and Python stdlib.
# No additional pip deps needed.

cp /solution/analyze.py /app/analyze.py
cd /app
python3 analyze.py
