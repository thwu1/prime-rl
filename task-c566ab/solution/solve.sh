#!/bin/bash

# Copy implementation to /app/
cp /solution/walloc_native.h /app/walloc_native.h
cp /solution/walloc_native.c /app/walloc_native.c

# Verify the implementation compiles
gcc -O2 -Wall -Wno-unused-function -o /app/verify_compile \
    /app/walloc_native.c -c
if [ $? -ne 0 ]; then
    echo "ERROR: walloc_native.c failed to compile"
    exit 1
fi
rm -f /app/verify_compile

echo "Solution installed and compiles successfully."
