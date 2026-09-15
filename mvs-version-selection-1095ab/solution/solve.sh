#!/bin/bash

# Copy the complete MVS implementation
cp /solution/mvs_fixed.go /app/mvs.go

# Build the binary
cd /app && go build -o mvs .
