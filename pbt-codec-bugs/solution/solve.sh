#!/bin/bash

set -e

pip3 install hypothesis==6.82.0 pytest==8.2.0 -q

# Apply bug fixes, write PBT tests, and produce bug taxonomy
python3 /solution/solve_helper.py

# Verify PBT tests pass against the fixed codec
cd /app
python3 -m pytest tests/test_pbt.py -v --tb=short

# Verify existing unit tests still pass
python3 -m pytest tests/test_basic.py -v --tb=short

# Verify with the verification test suite
python3 -m pytest /tests/test_state.py -v --tb=short
