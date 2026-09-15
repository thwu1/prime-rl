#!/bin/bash

# Deploy the implementation (remove existing empty dir to avoid nesting)
rm -rf /app/labs
cp -r /solution/labs /app/labs

# Verify correctness against reference database
python3 /solution/verify.py
