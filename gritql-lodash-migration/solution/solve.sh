#!/bin/bash

set -e

cd /app

# Write the GritQL pattern files
python3 /solution/write_pattern.py

# The sealed verifier runs the inline and apply checks with explicit per-call
# timeouts. Do not duplicate them here: a wedged Grit runtime would otherwise
# hold an oracle VM for the full session timeout before scoring can begin.
echo "GritQL migration patterns installed."
