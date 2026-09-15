#!/usr/bin/env bash

# Replace broken files with corrected versions
cp /solution/compile_fixed.go /app/compile.go
cp /solution/vm_fixed.go /app/vm.go
cp /solution/disasm_impl.go /app/disasm.go

# Build the evaluator
cd /app
go build -o /app/evaluator .
