#!/bin/bash

# Copy the complete implementation into the project
cp /solution/lib_solution.rs /app/src/lib.rs

# Build and run
cd /app
cargo build --release 2>&1
cargo run --release 2>&1
