#!/bin/bash

# Deploy the fixed allocator
cp /solution/allocator_fixed.py /app/allocator.py

# Run on the provided workload
cd /app && python3 allocator.py
