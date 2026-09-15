#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 scipy==1.14.1 -q

# Ensure input files are available in /app/
if [ ! -f /app/survey.csv ]; then
    cp /opt/taskdata/survey.csv /app/survey.csv 2>/dev/null || true
fi
if [ ! -f /app/prediction_grid.csv ]; then
    cp /opt/taskdata/prediction_grid.csv /app/prediction_grid.csv 2>/dev/null || true
fi

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
