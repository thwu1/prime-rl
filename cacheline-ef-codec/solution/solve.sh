#!/bin/bash

# Copy the implementation to /app/
cp /solution/ptrhash_impl.c /app/ptrhash.c

# Compile
gcc -O2 -std=c11 -Wall -Wextra -o /app/ptrhash_test \
    /app/ptrhash.c /tests/test_main.c -I/app -lm

# Sanity checks
echo "=== Verifying n=100 ==="
/app/ptrhash_test verify 100

echo "=== Verifying n=10000 ==="
/app/ptrhash_test verify 10000

echo "=== Verifying n=100000 ==="
/app/ptrhash_test verify 100000
