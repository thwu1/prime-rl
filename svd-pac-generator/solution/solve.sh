#!/bin/bash

# Copy generator to /app and run it
cp /solution/generator.py /app/generate.py
cd /app
python3 generate.py

# Verify compilation
cd /app/generated-pac && cargo build

# Verify tests pass
cd /app/test_harness && cargo test -- --test-threads=1
