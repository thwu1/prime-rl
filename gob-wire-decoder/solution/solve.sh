#!/bin/bash

set -e

# Replace the broken main.go with the fixed version
cp /solution/main_fixed.go /app/gobdecode/main.go

# Build
cd /app/gobdecode
go build -o /app/gobdecode/gobdecode .
echo "gobdecode built successfully"
