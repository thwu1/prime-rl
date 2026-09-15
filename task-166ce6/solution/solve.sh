#!/bin/bash

cd /app

# Step 1: Build all three C implementations
echo "=== Building implementations ==="
make -C /app/implementations all
if [ $? -ne 0 ]; then
    echo "ERROR: Build failed"
    exit 1
fi

# Step 2: Run the audit and attack
python3 /solution/attack.py
