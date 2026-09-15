#!/bin/bash

cd /app

# Apply all code modifications
python3 /solution/implement.py

# Build and run full test suite
go build ./...
go test ./... -count=1 -timeout=120s
