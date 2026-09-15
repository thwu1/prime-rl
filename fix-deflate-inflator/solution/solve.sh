#!/usr/bin/env bash


set -e
cd /app

python3 /solution/apply_fixes.py src/main.rs

cargo build --release 2>&1
