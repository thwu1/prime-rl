#!/bin/bash

set -e

# Fix all 4 bugs in the pipeline, then regenerate the mesh report
cd /app
python3 /solution/fix_bugs.py
python3 /app/pipeline/run.py
