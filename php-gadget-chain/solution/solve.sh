#!/bin/bash

# Install solution dependencies
pip3 install requests==2.32.3 -q

# Run the full audit, exploit, and mitigation solution
python3 /solution/exploit.py
