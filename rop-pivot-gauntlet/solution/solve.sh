#!/bin/bash

# Install solution dependencies
pip3 install pwntools==4.12.0 -q 2>/dev/null

# Deploy the exploit
cp /solution/exploit_helper.py /app/exploit.py

# Run it
python3 /app/exploit.py
