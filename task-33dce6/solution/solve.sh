#!/bin/bash

cd /app

# Analyze reference data and apply targeted engine fixes
python3 /solution/fix_engine.py

# Derive behavioral specification from the corrected engine
python3 /solution/derive_spec.py
