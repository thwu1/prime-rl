#!/bin/bash

# Compile the C++ tqdist binary
cd /app/tqdist && make

# Copy solution tool
cp /solution/quartet_tool.py /app/quartet_tool.py
chmod +x /app/quartet_tool.py
