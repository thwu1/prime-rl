#!/bin/bash

# Fix all semantic bugs in the Rust transpilation and produce audit
python3 /solution/fix_bugs.py

# Rebuild the Rust project
cd /app/rust_src && cargo build --release

# Verify by comparing outputs against C reference
gcc -O2 -o /app/c_src/record_processor /app/c_src/record_processor.c
/app/c_src/record_processor /app/data/input.txt > /tmp/c_out.txt
/app/rust_src/target/release/record_processor /app/data/input.txt > /tmp/rust_out.txt

if diff -q /tmp/c_out.txt /tmp/rust_out.txt > /dev/null 2>&1; then
    echo "SUCCESS: Rust output matches C reference"
else
    echo "FAILURE: Outputs still differ"
    diff /tmp/c_out.txt /tmp/rust_out.txt
    exit 1
fi

# Verify audit file exists
if [ -f /app/transpilation_audit.json ]; then
    echo "Audit report written to /app/transpilation_audit.json"
else
    echo "FAILURE: Audit report missing"
    exit 1
fi
