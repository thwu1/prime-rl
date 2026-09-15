#!/bin/bash
set -e

# Apply all 5 fixes to the mseries library
python3 /solution/fix_mseries.py

# Verify the fixed library loads without error
Rscript --vanilla -e 'source("/app/mseries.R"); cat("Library loads OK\n")'
