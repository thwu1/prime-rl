#!/usr/bin/env bash

set -euo pipefail

# Deploy the corrected regex engine
cp /solution/regex_engine_fixed.c /app/regex_engine.c

cd /app
make clean && make

# Build the shared library
gcc -shared -fPIC -o libposixre.so regex_engine.c
