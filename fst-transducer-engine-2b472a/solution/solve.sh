#!/bin/bash

set -e

# Copy solution source to /app
cp /solution/Cargo.toml /app/Cargo.toml
mkdir -p /app/src
cp /solution/src/main.rs /app/src/main.rs

# Build the project
cd /app
cargo build --release
