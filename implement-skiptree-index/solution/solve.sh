#!/bin/bash

# Deploy the working DuckDB-based index builder and query modules
cp /solution/index_impl.py /app/pipeline/index.py
cp /solution/query_impl.py /app/pipeline/query.py

# Build the index structures (reads SQLite, writes DuckDB)
python3 /app/pipeline/api.py build
