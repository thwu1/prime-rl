#!/bin/bash


set -e

# Copy the free list implementation
cp /solution/freelist_impl.go /app/freelist.go

# Copy the modified KV store with free list integration
cp /solution/kv_impl.go /app/kv.go

# Build
cd /app && go build -o /app/kvtool .

echo "Solution applied and built successfully."
