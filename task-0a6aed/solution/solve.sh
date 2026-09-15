#!/bin/bash

pip3 install redis==5.2.1 -q

# Start Redis as ground-truth reference for validation
redis-server --daemonize yes
sleep 1

# Generate and validate both the sorted set engine and RESP server
python3 /solution/implement.py
