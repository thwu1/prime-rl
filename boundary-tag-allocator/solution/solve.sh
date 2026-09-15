#!/bin/bash

# Copy fixed allocator source to /app
cp /solution/myalloc.c /app/myalloc.c

# Compile as a position-independent shared library
gcc -O2 -fPIC -shared -Wno-deprecated-declarations \
    -o /app/libmyalloc.so /app/myalloc.c -lpthread

echo "Built /app/libmyalloc.so successfully"
