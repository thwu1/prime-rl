#!/bin/bash

# Compile the structural verifier
gcc -O2 -o /app/tools/pgverify /app/tools/pgverify.c

# Install the recovery and repair tool
cp /solution/recover.py /app/recover
chmod +x /app/recover
