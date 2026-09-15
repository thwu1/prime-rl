#!/usr/bin/env bash

set -euo pipefail

cd /app

# Apply all fixes
python3 /solution/fix_shaper.py

# Normal build and test
make clean all
./test_shaper all

# ASAN build and test
make clean all \
    CFLAGS="-Wall -Wextra -std=c11 -g -O0 -fsanitize=address -fno-omit-frame-pointer" \
    LDFLAGS="-fsanitize=address -static-libasan"
ASAN_OPTIONS=detect_leaks=0 ./test_shaper all
