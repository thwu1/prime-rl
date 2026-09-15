#!/bin/bash

# Install solution dependencies
pip3 install requests==2.32.3 flask==3.1.1 -q

# Apply all fixes
python3 /solution/apply_fixes.py
