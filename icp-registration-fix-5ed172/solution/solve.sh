#!/bin/bash

set -e

# Replace the buggy registration implementation with the fixed version
cp /solution/fixed_registration.cpp /app/src/registration.cpp

# Rebuild the project
mkdir -p /app/build && cd /app/build && cmake .. && make -j2
