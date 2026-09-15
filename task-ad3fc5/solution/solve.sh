#!/bin/bash

# Install the complete HSM dispatch engine implementation
cp /solution/hsm_impl.c /app/hsm.c

# Build directly with gcc (avoids dependency on Makefile)
cd /app
gcc -std=c11 -Wall -Wextra -Wpedantic -o hsm_test main.c hsm.c test_sm.c
