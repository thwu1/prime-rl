#!/usr/bin/env bash

set -euo pipefail

# Copy the fixed MicroHaxl.hs over the broken one
cp /solution/MicroHaxl_fixed.hs /app/MicroHaxl.hs

echo "Solution applied: replaced /app/MicroHaxl.hs with fixed version"
