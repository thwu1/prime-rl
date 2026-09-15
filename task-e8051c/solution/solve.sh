#!/bin/bash

python3 -m pip install flask==3.0.3 -q

# Analyze conformance report and fix all violations (code + data)
python3 /solution/fix_bugs.py
