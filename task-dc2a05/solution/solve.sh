#!/bin/bash

# Deploy the lock-free concurrent hash map implementation
python3 /solution/generate_impl.py

# Build
cd /app && make all
