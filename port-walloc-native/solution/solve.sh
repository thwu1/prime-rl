#!/bin/bash

# Copy solution files into the working directory
cp /solution/walloc_native.c /app/walloc_native.c
cp /solution/walloc_native.h /app/walloc_native.h

# Compile as shared library to verify
gcc -shared -fPIC -O2 -DNDEBUG -o /app/libwalloc_native.so /app/walloc_native.c
echo "Compilation successful"
