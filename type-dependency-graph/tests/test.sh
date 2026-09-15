#!/bin/bash


pip3 install pytest==8.3.4 -q

# Build and run the analyzer
cd /app
npm install 2>&1 | tail -3
npx tsc 2>&1
BUILD_EXIT=$?

if [ $BUILD_EXIT -ne 0 ]; then
    echo "TypeScript compilation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

node dist/analyzer.js target-project/tsconfig.json > /tmp/analyzer_output.json 2>/tmp/analyzer_error.log
RUN_EXIT=$?

if [ $RUN_EXIT -ne 0 ]; then
    echo "Analyzer execution failed"
    cat /tmp/analyzer_error.log
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
