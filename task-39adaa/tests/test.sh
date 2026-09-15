#!/bin/bash

pip3 install pytest==8.3.4 -q

# Run the pipeline to generate results.json (if cad_eval.py exists)
cd /app
if [ -f /app/cad_eval.py ]; then
    python3 /app/cad_eval.py /app/manifest.json /app/results.json 2>/dev/null || true
fi

# Run pytest and capture exit code
pytest_exit=0
python3 -m pytest /tests/test_state.py -v || pytest_exit=$?

# Write reward
mkdir -p /logs/verifier
if [ $pytest_exit -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $pytest_exit
