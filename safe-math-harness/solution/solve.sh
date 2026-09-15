#!/bin/bash

# Fix 1: Install corrected UB-safe arithmetic wrappers
cp /solution/fixed_safe_math.h /app/safe_math.h

# Fix 2: Restore uint32_t PRNG to eliminate signed overflow UB in generator
cp /solution/fixed_expr_gen.c /app/expr_gen.c

# Fix 3: Fix cross-compiler harness ($CC -> $cc variable reference)
cp /solution/fixed_harness.sh /app/harness.sh
chmod +x /app/harness.sh

# Fix 4: Fix Makefile coverage target (add --coverage, complete recipe, clean gcov files)
cp /solution/fixed_Makefile /app/Makefile

# Rebuild
make -C /app clean
make -C /app expr_gen
