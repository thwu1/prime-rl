#!/bin/bash

set -e

# Copy the corrected Rust source into the project
cp /solution/main.rs /app/arrow_ipc_reader/src/main.rs

# Build the project
cd /app/arrow_ipc_reader
cargo build --release 2>&1
