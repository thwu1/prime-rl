#!/bin/bash

pip3 install pytest==8.3.4 -q

python3 /solution/solver.py

echo "Running verification..."
pytest /tests/test_state.py -v
