#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 scipy==1.14.1 scikit-learn==1.5.2 -q

# Ensure synthetic EEG data exists (regenerate if Docker build artifacts were cleared)
if [ ! -f /app/data/metadata.npz ]; then
    python3 /opt/generate_data.py
fi

cd /app
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
