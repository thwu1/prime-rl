#!/bin/bash

export PATH="/usr/local/cargo/bin:/root/.cargo/bin:$PATH"
export CARGO_HOME="${CARGO_HOME:-/usr/local/cargo}"
export RUSTUP_HOME="${RUSTUP_HOME:-/usr/local/rustup}"

# Install Rust if not available (fallback if Docker build used different paths)
if ! command -v cargo &> /dev/null; then
    export CARGO_HOME="/usr/local/cargo"
    export RUSTUP_HOME="/usr/local/rustup"
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain nightly
    export PATH="/usr/local/cargo/bin:$PATH"
    rustup component add miri
    cargo miri setup
fi

set -e

cd /app

# Classify each function by running Miri under both aliasing models
python3 /solution/classify.py

# Install the fixed implementations
cp /solution/fixed.rs /app/src/fixed.rs

echo "Solution complete."
