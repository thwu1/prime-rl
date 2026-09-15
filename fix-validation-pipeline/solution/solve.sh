#!/bin/bash

set -e

cd /app

# === Step 1: Fix missing createTemplate overload in 1:1 implementation ===
echo "=== Fixing 1:1 implementation (missing pure virtual override) ==="
python3 /solution/fix_impl.py

# === Step 2: Fix eval_quality.h API design violations ===
echo "=== Fixing eval_quality.h design violations ==="
python3 /solution/fix_header.py

# === Step 3: Create quality implementation and pipeline ===
echo "=== Creating quality assessment track ==="
python3 /solution/create_quality_track.py

# === Step 4: Run unified validation pipeline ===
echo "=== Running unified validation ==="
chmod +x scripts/*.sh run_validate.sh
./run_validate.sh
