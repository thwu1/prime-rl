#!/usr/bin/env bash

# Replace the broken pipeline.c with the fixed version
cp /solution/pipeline_fixed.c /app/pipeline.c

# Build
gcc -O2 -o /app/pipeline /app/pipeline.c -I/app/include
