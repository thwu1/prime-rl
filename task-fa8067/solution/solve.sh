#!/usr/bin/env bash

set -euo pipefail

# Replace the skeleton with the full implementation
cp /solution/blockht.c /app/blockht.c

# Build the shared library
make -C /app clean
make -C /app
