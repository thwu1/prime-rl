#!/bin/bash

pip3 install pytest==8.3.4 -q

# Generate hidden test programs
python3 /tests/gen_extra_programs.py

cd /app
pytest /tests/test_state.py -v
pytest_exit_code=$?

mkdir -p /logs/verifier
if [ $pytest_exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $pytest_exit_code
