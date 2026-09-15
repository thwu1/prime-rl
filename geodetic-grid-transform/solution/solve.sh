#!/bin/bash

set -e

cd /app

# Apply all bug fixes via analysis script
python3 /solution/fix_bugs.py

# Recompile
bash /app/compile.sh

echo "All fixes applied and compiled successfully."
