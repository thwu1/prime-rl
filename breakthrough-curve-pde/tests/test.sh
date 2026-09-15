#!/bin/bash

pip3 install pytest==8.3.4 numpy==1.26.4 scipy==1.13.1 -q

cd /app

# Run the analysis script (allow failure; pytest will catch missing output)
python3 analyze.py 2>&1 || true

# Run tests
pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $exit_code
