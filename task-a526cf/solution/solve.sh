#!/usr/bin/env bash

set -euo pipefail

cd /app

# Install the correct rasterizer implementation
cp /solution/rasterizer_impl.c /app/rasterizer.c

# Rebuild
make clean
make

# Verify binary was produced
test -f /app/compositor
