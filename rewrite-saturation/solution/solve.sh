#!/bin/bash

cp /solution/egraph_optimizer.py /app/optimize.py
mkdir -p /app/output

for f in /opt/eqsat/benchmarks/expr*.sexp; do
    python3 /app/optimize.py "$f"
done
