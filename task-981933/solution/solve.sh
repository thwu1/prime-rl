#!/bin/bash

# No external pip deps needed — compiler uses only Python stdlib
mkdir -p /app/models /app/results
cp /solution/compiler.py /app/compiler.py
python3 /app/compiler.py
