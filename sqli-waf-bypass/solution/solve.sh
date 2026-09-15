#!/bin/bash

# Install solution dependencies
pip3 install requests==2.32.3 -q 2>/dev/null

# Ensure services are running
/app/start_server.sh

# Run the multi-service exploit
python3 /solution/exploit.py
