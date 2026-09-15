#!/bin/bash

# Build the Rust reference checker
cd /app/data/market_split/checker && cargo build --release 2>&1

mkdir -p /app/solutions
python3 /solution/verify_pipeline.py
