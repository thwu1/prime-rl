#!/bin/bash

cp /solution/emulator.py /app/emulator.py
chmod +x /app/emulator.py

# Verify copy succeeded
if [ ! -f /app/emulator.py ]; then
    echo "ERROR: Failed to copy emulator.py to /app/"
    exit 1
fi

# Quick smoke test - run emulator on simplest program
python3 /app/emulator.py /app/programs/test_primitives.hex /tmp/smoke_test.raw
if [ $? -ne 0 ]; then
    echo "ERROR: Emulator smoke test failed"
    exit 1
fi
