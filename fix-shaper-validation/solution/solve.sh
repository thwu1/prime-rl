#!/usr/bin/env bash

set -euo pipefail

# Copy the corrected source file and rebuild
cp /solution/shaper_fixed.c /app/shaper.c
make -C /app clean all

echo "Library rebuilt with all fixes applied."
