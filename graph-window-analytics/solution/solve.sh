#!/bin/bash

set -e

# Replace the broken analyze.sql with the fixed version
cp /solution/fixed_analyze.sql /app/analyze.sql

# Run the pipeline
bash /app/run.sh
