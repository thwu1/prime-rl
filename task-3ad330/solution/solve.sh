#!/bin/bash


# Install solution dependencies
pip3 install onnx==1.17.0 onnxruntime==1.20.1 numpy==2.1.3 -q

cd /app

# Write MLA implementation
python3 /solution/implement_mla.py

# Write C RoPE extension and fix Makefile
python3 /solution/implement_rope.py

# Build C extension
make -C /app build

# Write and run ONNX export
python3 /solution/implement_export.py
python3 /app/export_onnx.py
