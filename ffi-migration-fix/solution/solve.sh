#!/bin/bash

export PATH="/usr/local/cargo/bin:$PATH"

# Part 1: Fix build.rs, lib.rs, and ffi.rs bugs
python3 /solution/apply_fixes.py

# Part 2: Install the correct safe wrapper module
cp /solution/wrapper.rs /app/src/wrapper.rs

# Verify the fix worked
cd /app
cargo build 2>&1
echo "Build exit code: $?"

cargo test -- --test-threads=1 2>&1
echo "Test exit code: $?"
