#!/bin/bash


pip3 install protobuf==5.29.3 pyarrow==18.1.0 numpy==2.1.3 -q

# Compile the proto schema
cd /app
protoc --python_out=. --proto_path=. reaction.proto

# Deploy the analyzer
cp /solution/ord_analyze.py /app/ord_analyze.py
