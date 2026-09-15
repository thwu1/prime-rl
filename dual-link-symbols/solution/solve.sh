#!/bin/bash

set -e
cd /app

# Build v5 library object
gcc -fPIC -Wall -O2 -c /app/libprocessor_v5/processor.c -o /app/v5_processor.o \
    -I/app/libprocessor_v5

# Build the compatibility shim
gcc -fPIC -Wall -O2 -c /solution/shim.c -o /app/shim.o \
    -I/app -I/app/libprocessor_v5

# Link shim + v5 into a shared library with the correct SONAME
gcc -shared -Wl,-soname,libprocessor.so.2 \
    -o /app/libprocessor.so.2 \
    /app/shim.o /app/v5_processor.o -lm

# Run legacy_app
export LD_LIBRARY_PATH=/app:${LD_LIBRARY_PATH:-}
/app/legacy_app

# Generate compatibility assessment through programmatic analysis
python3 /solution/analyze.py
