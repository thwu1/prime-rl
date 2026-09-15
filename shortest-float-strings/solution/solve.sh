#!/bin/bash

cd /app

# Build the C converters
make

# Build the Go round-trip verifier
go build -o /app/verify_bin /app/verify.go

# Run the solver
python3 /solution/solver.py

# Verify with Go verifier
/app/verify_bin
