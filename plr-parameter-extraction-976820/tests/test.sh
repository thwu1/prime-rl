#!/bin/bash


# Install test dependencies
pip3 install pytest==8.3.4 -q

# Generate test fixtures (creates /app/data/ CSVs and /tests/ground_truth.json)
echo "Generating test fixtures..."
python3 /tests/generate_fixtures.py
if [ $? -ne 0 ]; then
    echo "Fixture generation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the solver's analysis tool
echo "Running PLR analysis tool..."
if [ -f /app/plr_analyze.py ]; then
    python3 /app/plr_analyze.py --input /app/data --output /app/results
    ANALYZE_EXIT=$?
    if [ $ANALYZE_EXIT -ne 0 ]; then
        echo "Analysis tool failed with exit code $ANALYZE_EXIT"
        mkdir -p /logs/verifier
        echo "0.0" > /logs/verifier/reward.txt
        exit 1
    fi
else
    echo "ERROR: /app/plr_analyze.py not found"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
echo "Running verification tests..."
pytest /tests/test_state.py -v
PYTEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
