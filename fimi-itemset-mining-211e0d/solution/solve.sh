#!/bin/bash

# Fix all pipeline components

# 1. Replace buggy AWK normalizer with fixed version
cp /solution/normalize_fixed.awk /app/lib/normalize.awk

# 2. Replace buggy Python miner with fixed version
cp /solution/miner_fixed.py /app/lib/miner.py

# 3. Replace buggy shell entry point with fixed version
cp /solution/fim_fixed.sh /app/fim
chmod +x /app/fim

# 4. Replace buggy Makefile with fixed version
cp /solution/Makefile_fixed /app/Makefile

# 5. Initialize SQLite database and run pipeline
rm -f /app/results.db
sqlite3 /app/results.db < /app/schema/results.sql
make -C /app pipeline
