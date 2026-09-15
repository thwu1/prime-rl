#!/usr/bin/env bash

set -euo pipefail

python3 /solution/fix_workspace.py

cd /app
echo "=== Verifying: cargo check --workspace ==="
cargo check --workspace

echo "=== Verifying: cargo check -p signal-storage ==="
cargo check -p signal-storage

echo "=== Verifying: cargo check -p signal-net ==="
cargo check -p signal-net

echo "=== Verifying: cargo test -p signal-net ==="
cargo test -p signal-net

echo "=== Verifying migration_report.toml exists ==="
cat /app/migration_report.toml

echo "=== All checks passed ==="
