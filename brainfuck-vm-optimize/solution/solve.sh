#!/bin/bash

# Write the fixed and optimized Go source files
cp /solution/instruction_fixed.go /app/instruction.go
cp /solution/compiler_fixed.go /app/compiler.go
cp /solution/machine_fixed.go /app/machine.go

# Clean Go build cache and rebuild
cd /app
go clean -cache 2>/dev/null
go build -o /app/bfvm /app/
