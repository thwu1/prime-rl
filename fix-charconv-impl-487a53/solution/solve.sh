#!/usr/bin/env bash

set -euo pipefail

# Replace the buggy implementation with the fixed version
cp /solution/charconv_fixed.cpp /app/charconv.cpp

# Build
make -C /app clean
make -C /app

# Verify with the smoke test
/app/run_tests
