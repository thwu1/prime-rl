#!/bin/bash

# Copy the full hardened allocator implementation into /app
cp /solution/allocator_impl.c /app/allocator.c

# Build to verify
cd /app && make clean && make
