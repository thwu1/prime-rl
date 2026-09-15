#!/bin/bash

# Copy the complete solution into the project
cp /solution/solution_main.rs /app/src/main.rs

cd /app
cargo build --release 2>&1
cargo run --release 2>&1
