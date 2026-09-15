#!/bin/bash

set -euo pipefail

mkdir -p /app/layout_solver

cp /solution/types.py /app/layout_solver/types.py
cp /solution/__init__.py /app/layout_solver/__init__.py
cp /solution/solver_impl.py /app/layout_solver/solver.py
