#!/usr/bin/env bash

# Copy the reference optimizer and helpers to /app
cp /solution/optimizer_ref.py /app/optimizer.py
cp /solution/cfg_to_dot.py /app/cfg_to_dot.py
cp /solution/Makefile /app/Makefile

# Run the full pipeline
cd /app && make all
