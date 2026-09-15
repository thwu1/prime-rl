#!/bin/bash

pip3 install pytest==8.3.4 -q

# Run solver on each board with timeout, saving moves to temp files
for i in 0 1 2 3 4; do
    timeout 50 python3 /app/solver.py "/app/boards/board_${i}.txt" > "/tmp/moves_${i}.txt" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "Solver failed or timed out on board ${i}" >&2
        echo "" > "/tmp/moves_${i}.txt"
    fi
done

# Run validation tests
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
