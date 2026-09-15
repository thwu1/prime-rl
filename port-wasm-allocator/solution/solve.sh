#!/bin/bash

set -e

# Copy the solution implementation into the app directory
cp /solution/walloc_native.c /app/walloc_native.c

# Build
cd /app && make clean && make
