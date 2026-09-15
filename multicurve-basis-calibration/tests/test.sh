#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Compile Java source
mkdir -p bin
javac -d bin /app/src/calibrator/*.java 2>&1
if [ $? -ne 0 ]; then
    echo "FAIL: Java compilation error"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run calibrator to produce results.json
java -cp bin calibrator.MulticurveCalibrator 2>&1
if [ $? -ne 0 ]; then
    echo "FAIL: Runtime error"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run verification tests
RESULT=0
python3 -m pytest /tests/test_state.py -v 2>&1 || RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
