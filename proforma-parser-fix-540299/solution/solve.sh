#!/bin/bash

# Replace the broken parser with the fixed version
cp /solution/fixed_parser.rs /app/src/parser.rs

cd /app
cargo build --release 2>&1

./target/release/proforma_parse /app/input.txt /app/output.json 2>&1
