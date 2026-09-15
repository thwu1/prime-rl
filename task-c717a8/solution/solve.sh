#!/usr/bin/env bash

set -e

# Install the solution: replace skeleton files with complete implementations
cp /solution/solution_datatype.rs /app/src/datatype.rs
cp /solution/solution_expr.rs /app/src/expr.rs

# Build and test
cd /app
cargo build
cargo test
