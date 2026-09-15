#!/bin/bash


set -e

cd /app

# Fix Bug 1: KEM return-value confusion in kem.c
# secops_rsa_public_encrypt returns -1 on failure (truthy in C).
# The check "if (ret)" incorrectly treats -1 as success.
python3 /solution/fix_kem.py

# Fix Bug 2: Missing parameter validation in kdf.c
# Salt type and keylength are used without validation.
python3 /solution/fix_kdf.py

# Write regression tests
cp /solution/test_security.c /app/tests/test_security.c

# Rebuild
make clean all

# Run basic tests
make test

# Build and run regression tests
gcc -Wall -Wextra -std=c11 -I include -o test_security tests/test_security.c libsecops.a
./test_security
