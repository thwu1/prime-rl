#!/bin/bash

set -euo pipefail

cd /app

# Run the complete solution: parse traces, evaluate, report, fix
python3 /solution/solve_task.py
