#!/usr/bin/env bash

set -e

# Create Rust project structure at /app
mkdir -p /app/src

cp /solution/Cargo.toml /app/Cargo.toml
cp /solution/main.rs /app/src/main.rs

cd /app
cargo build --release
