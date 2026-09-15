#!/bin/bash

# Restore lib.rs and write the complete fixed FFI bridge implementation
python3 /solution/write_ffi.py

# Clean any stale build artifacts from prior agent runs, then rebuild
cd /app/rust-sortedset && cargo clean 2>/dev/null; cargo build --release
