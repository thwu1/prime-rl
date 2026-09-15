#!/bin/bash

pip3 install pyyaml==6.0.2 -q
cp /solution/solver.py /app/analyze.py
cd /app
python3 /app/analyze.py
