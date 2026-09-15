#!/bin/bash

# No additional pip dependencies needed - solution uses only stdlib

# Deploy the search tool
cp /solution/sasearch_impl.py /app/sasearch.py

# Build the index
python3 /app/sasearch.py index /app/corpus /app/index.bin
