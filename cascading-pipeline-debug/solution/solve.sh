#!/bin/bash

set -e

# --- Fix 1: Config generator SQL query (add schema filter) ---
python3 /solution/fix_configgen.py

# --- Fix 2: Go prefix manager (query param bug + circuit breaker) ---
cp /solution/main_fixed.go /app/prefixmgr/main.go
cd /app/prefixmgr && go build -o /app/bin/prefixmgr .
echo "[build] Go prefix manager rebuilt"

# --- Fix 3: Rust config loader (graceful error handling) ---
cp /solution/main_fixed.rs /app/loader/src/main.rs
cd /app/loader && cargo build --release && cp target/release/config_loader /app/bin/config_loader
echo "[build] Rust config loader rebuilt"

# --- Install pipeline validator ---
cp /solution/validate_pipeline.py /app/validate_pipeline.py
chmod +x /app/validate_pipeline.py

# --- Regenerate config with fixed generator ---
python3 /app/configgen/generate.py

# --- Verify end-to-end pipeline ---
echo "[verify] Testing config loader with generated config..."
/app/bin/config_loader /app/config/features.json

echo "[verify] Running pipeline validator..."
python3 /app/validate_pipeline.py

echo "[verify] All fixes applied and verified"
