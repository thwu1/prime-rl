#!/bin/bash

# Copy the corrected C source and recompile
cp /solution/acvp_module.c /app/acvp_module.c
gcc -O2 -o /app/acvp_module /app/acvp_module.c -lcrypto
