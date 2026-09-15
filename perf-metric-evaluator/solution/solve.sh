#!/bin/bash

cd /app

# Fix extraction and pipeline bugs, then run
python3 /solution/solve.py

# Run the full pipeline (extraction + evaluation)
bash /app/run.sh
