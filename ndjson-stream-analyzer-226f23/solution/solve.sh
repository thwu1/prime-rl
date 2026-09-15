#!/bin/bash

set -e

cd /app

# Download simdjson if not already present
bash setup_simdjson.sh

# Replace the broken source with the fixed version
cp /solution/stream_analyzer_fixed.cpp /app/stream_analyzer.cpp

# Build the fixed tool
make clean all
echo "stream_analyzer built successfully."
