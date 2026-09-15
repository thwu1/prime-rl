#!/usr/bin/env bash

cd /app

# Install the migration analyzer tool
cp /solution/migration_analyzer.py /app/migration_analyzer.py

# Run the analyzer: generate report (pre-fix state), then apply config fixes
python3 /app/migration_analyzer.py --apply

# Fix the build.rs code bug: polynomial rolling hash -> FNV-1a 64-bit
# This is a code-level bug that config analysis cannot detect.
python3 /solution/fix_build_rs.py
