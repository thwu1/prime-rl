#!/bin/bash

# Clean previous outputs and re-run pipeline for a fresh test
rm -f /app/tracks.db /app/report.json
python3 /app/pipeline.py /app/stations /app/tracks.db /app/report.json 2>/dev/null

# Run pytest and capture exit code
pytest /tests/test_state.py -v --tb=short 2>&1
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
