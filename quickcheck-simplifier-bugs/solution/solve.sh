#!/bin/bash

export RUSTUP_HOME=/opt/rustup
export CARGO_HOME=/opt/cargo
export PATH="/opt/cargo/bin:${PATH}"

cd /app
python3 /solution/solve.py
cargo test
