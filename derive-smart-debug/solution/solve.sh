#!/bin/bash

# Install the proc macro implementation
cp /solution/smart_debug_impl.rs /app/smart_debug/src/lib.rs

# Build and test
cd /app
cargo build 2>&1
cargo test 2>&1
