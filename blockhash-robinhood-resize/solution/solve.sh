#!/bin/bash

set -e

# Copy the solution implementation into place
cp /solution/hashtable_impl.c /app/hashtable.c

# Build the shared library
make -C /app clean
make -C /app

echo "Solution built successfully."
