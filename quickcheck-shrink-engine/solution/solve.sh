#!/bin/bash

# Install solution dependencies
pip3 install pytest==8.3.4 -q

# Ensure app directory structure exists
mkdir -p /app/pbt

# Deploy the correct pbt package implementations
cp /solution/gen.py /app/pbt/gen.py
cp /solution/shrink_impl.py /app/pbt/shrink.py
cp /solution/engine_impl.py /app/pbt/engine.py
cp /solution/structured_impl.py /app/pbt/structured.py

cat > /app/pbt/__init__.py << 'PYEOF'
"""Property-based testing library."""
from pbt.gen import Gen
PYEOF

# Find counterexamples and fix the buggy target functions
cd /app && python3 /solution/run_and_fix.py

# Evaluate properties
cd /app && python3 /solution/property_evaluator.py
