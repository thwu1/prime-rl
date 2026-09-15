#!/bin/bash

export PATH="/usr/local/cargo/bin:/usr/local/bin:$PATH"
export CARGO_HOME="/usr/local/cargo"

cp /solution/main.rs /app/src/main.rs
cd /app
cargo build --release --manifest-path /app/Cargo.toml
/app/target/release/egraph-optimizer
