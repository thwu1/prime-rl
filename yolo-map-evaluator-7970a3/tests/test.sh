#!/bin/bash

pip3 install pytest==8.3.4 pycocotools==2.0.8 numpy==1.26.4 pyyaml==6.0.2 -q

# Generate synthetic dataset (deterministic, seed=42)
python3 /app/data/generate_dataset.py

# Run the pipeline (solver should have fixed all components)
rm -f /app/results.json
make -C /app evaluate 2>&1 || true

# Run tests
RESULT=$(pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?

echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
