#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Apply all seven fixes (C source + rebuild + Python pipeline) and verify
python3 /solution/apply_fixes.py
