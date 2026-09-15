#!/bin/bash

set -e

# Step 1: Install the working free list and KV store implementations
cp /solution/freelist_impl.go /app/freelist.go
cp /solution/kv_impl.go /app/kv.go

cd /app

# Verify compilation
go build -o /dev/null .

# Step 2: Build a standalone binary for I/O tracing
cp /app/main.go /app/main.go.bak
cp /solution/trace_main.go /app/main.go
go build -o /app/trace_bin .
cp /app/main.go.bak /app/main.go
rm /app/main.go.bak

# Step 3: Run the trace binary (captures I/O trace log and creates database)
rm -f /tmp/trace_test.db /tmp/io_trace.log
/app/trace_bin

# Step 4: Generate I/O protocol report from the trace log
python3 /solution/analyze_io.py

# Step 5: Generate meta page hex dump report using xxd
python3 /solution/analyze_meta.py

# Cleanup
rm -f /app/trace_bin

echo "Solution installed and verification reports generated."
