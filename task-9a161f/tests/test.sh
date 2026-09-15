#!/bin/bash

pip3 install pytest==8.3.4 -q

# Build the C verification tool
cd /app/tools && make -s undead-tool 2>&1
cd /app

# Generate an extra puzzle at test time to prevent hardcoded solutions
python3 /tests/generate_extra.py

# Clear any pre-existing outputs so we verify the tools actually run
rm -rf /app/solutions /app/generated
mkdir -p /app/solutions /app/generated

# Run the generator (if it exists)
if [ -f /app/generator.py ]; then
    python3 /app/generator.py || true
fi

# Run the solver (if it exists)
if [ -f /app/solver.py ]; then
    python3 /app/solver.py || true
fi

# Run verification tests
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
