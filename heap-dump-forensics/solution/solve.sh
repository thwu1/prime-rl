#!/bin/bash

# Deploy the heap validator tool
cp /solution/heap_validator.py /app/heap_validator.py
chmod +x /app/heap_validator.py

# Run the main forensics solver (produces report + flag)
python3 /solution/solve_heap.py
