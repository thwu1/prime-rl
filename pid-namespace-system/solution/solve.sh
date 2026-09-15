#!/bin/bash

# Copy the correct implementation into the project
cp /solution/lib_impl.rs /app/src/lib.rs

# Build the project
cd /app && cargo build --release
