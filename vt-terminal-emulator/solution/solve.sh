#!/bin/bash

# Copy the reference implementation and integration artifacts to /app
cp /solution/terminal.c /app/terminal.c
cp /solution/bindings.py /app/bindings.py
cp /solution/tmux_oracle.sh /app/tmux_oracle.sh
chmod +x /app/tmux_oracle.sh

# Build both the binary and shared library
cd /app && make
