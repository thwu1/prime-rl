#!/bin/bash

# Apply all fixes to the broken evaluation pipeline
python3 /solution/apply_fixes.py

# Run the fixed pipeline
/app/run_eval.sh
