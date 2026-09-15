#!/bin/bash

# Copy the reference header and implementation into place
cp /solution/analytics_solution.h /app/analytics.h
cp /solution/analytics_solution.c /app/analytics.c

# Build
cd /app
make clean
make
