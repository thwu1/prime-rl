#!/bin/bash

# Install solution dependencies
pip3 install cryptography==44.0.0 -q

cd /app
python3 /solution/forge_tuf.py
