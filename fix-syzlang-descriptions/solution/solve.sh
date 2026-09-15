#!/bin/bash


cd /app

# Fix the linter bugs first
python3 /solution/fix_linter.py

# Fix the syzlang descriptions
python3 /solution/fix_descriptions.py

# Verify the pipeline works
python3 /app/tools/syzlang_lint.py /app/include/vdma.h /app/sys/vdma.txt
