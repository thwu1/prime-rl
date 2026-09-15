#!/bin/bash

# Generate the AES-128 decryption module
python3 /solution/gen_decrypt.py

# Verify by compiling and simulating
cd /app && make clean && make test
