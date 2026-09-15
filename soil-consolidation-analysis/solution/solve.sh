#!/bin/bash

# Fix all pipeline components

# 1. Fix settlement engine (copy corrected version)
cp /solution/geosettle.py /app/geosettle.py

# 2. Fix Makefile (correct python command and dependencies)
cp /solution/Makefile /app/Makefile

# 3. Fix preprocessor (read site-specific params, fix output_times format)
cp /solution/preprocess.py /app/tools/preprocess.py

# 4. Fix result storage (correct SQL column order)
cp /solution/store_results.py /app/tools/store_results.py

# 5. Run the full pipeline
cd /app && make all
