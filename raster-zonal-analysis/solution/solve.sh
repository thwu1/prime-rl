#!/bin/bash

# Install solution dependencies
pip3 install scipy==1.13.1 -q

cd /app
python3 /solution/pipeline.py
