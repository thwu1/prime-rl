#!/bin/bash

set -euo pipefail

# Create passes directory if needed
mkdir -p /app/passes

# Deploy optimization pass modules
cp /solution/pass_const_fold.py /app/passes/const_fold.py
cp /solution/pass_copy_prop.py /app/passes/copy_prop.py
cp /solution/pass_dead_branch.py /app/passes/dead_branch.py
cp /solution/pass_unreachable.py /app/passes/unreachable.py
cp /solution/pass_dead_code.py /app/passes/dead_code.py
cp /solution/pass_algebraic_simp.py /app/passes/algebraic_simp.py
cp /solution/pass_cse.py /app/passes/cse.py

# Deploy pipeline configuration
cp /solution/pipeline_config.toml /app/pipeline.toml

# Verify the solution works
cd /app
ircc verify-all
