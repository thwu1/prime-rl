#!/bin/bash

pip3 install pytest==8.3.4 -q

# Run the analyzer to populate the database
python3 /app/vgdl_analyze.py --db /app/games.db --games /app/games/ --levels /app/levels/
ANALYZE_EXIT=$?

if [ $ANALYZE_EXIT -ne 0 ]; then
    echo "Analyzer failed with exit code $ANALYZE_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
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
