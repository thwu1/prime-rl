#!/bin/bash

set -e

export PATH="/usr/local/cargo/bin:/root/.cargo/bin:$PATH"

# Apply fixes: corrected engine library, triangle binary, and new SCC implementation
cp /solution/lib.rs /app/src/lib.rs
cp /solution/triangles.rs /app/src/bin/triangles.rs
cp /solution/scc.rs /app/src/bin/scc.rs

# Rebuild
cd /app
cargo build --release

# Run all programs
./target/release/transitive_closure
./target/release/triangles
./target/release/reaching_defs
./target/release/scc
