#!/bin/bash

set -e

# Replace the skeleton reconciler with the complete implementation.
cp /solution/reconciler_impl.go /app/engine/reconciler.go

# Verify the solution compiles.
cd /app && go build ./...
