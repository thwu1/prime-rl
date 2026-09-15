#!/bin/bash

# Replace buggy source files with correct implementations
cp /solution/varint.go /app/tscodec/varint.go
cp /solution/nearest_delta.go /app/tscodec/nearest_delta.go
cp /solution/nearest_delta2.go /app/tscodec/nearest_delta2.go
cp /solution/encoding.go /app/tscodec/encoding.go
cp /solution/dedup.go /app/tscodec/dedup.go
cp /solution/block.go /app/tscodec/block.go

# Run the tests to verify
cd /app && go test ./tscodec/ -count=1 -v
