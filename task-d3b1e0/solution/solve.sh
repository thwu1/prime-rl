#!/bin/bash

set -e
cd /app

# Ensure Go modules are available
go mod tidy 2>/dev/null || true

# Apply the MVCC implementation
python3 /solution/fix_mvcc.py
