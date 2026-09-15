#!/bin/bash

set -e

# Ensure the redact package directory exists
mkdir -p /app/redact

# Replace the broken encoder with the fixed implementation
cp /solution/encoder_fixed.go /app/redact/encoder.go

cd /app
go mod tidy
