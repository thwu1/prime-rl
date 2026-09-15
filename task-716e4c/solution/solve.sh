#!/bin/bash

set -e

# Copy the solution implementation into /app/
cp /solution/walloc_native_impl.c /app/walloc_native.c

# Verify it compiles as a shared library
cd /app
gcc -shared -fPIC -O2 -DNDEBUG -Wall -I/app -o /app/libwalloc.so /app/walloc_native.c
echo "Solution compiled successfully."
