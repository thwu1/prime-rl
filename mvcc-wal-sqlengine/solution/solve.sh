#!/usr/bin/env bash

pip3 install protobuf==4.25.5 -q

cd /app

# Generate protobuf Python code from the provided schema
protoc --python_out=. minidb/wal.proto

# Apply the implementation
python3 /solution/implement.py
