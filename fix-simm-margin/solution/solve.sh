#!/bin/bash

# Fix all build system and Java code defects in the ISDA SIMM calculator

cd /app

# Apply all fixes
python3 /solution/fix_simm.py

# Verify build works
ant compile
