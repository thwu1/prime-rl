#!/bin/bash

set -e

cd /app

# Initialize Go module and install YAML dependency
go mod init geochem
go get gopkg.in/yaml.v3@v3.0.1

# Copy solver source
cp /solution/solver.go /app/main.go

# Build
go build -o /app/geochem .

echo "Build complete. Solver at /app/geochem"
