#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Build LULESH from the agent's code
make clean 2>/dev/null
make 2>&1
BUILD_EXIT=$?

if [ $BUILD_EXIT -ne 0 ]; then
    echo "Build failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run primary test cases
./lulesh2.0 -s 10 -i 100 > /tmp/agent_output_s10_i100.txt 2>&1
./lulesh2.0 -s 15 -i 50 > /tmp/agent_output_s15_i50.txt 2>&1

# Run convergence test cases
./lulesh2.0 -s 8 -i 50 > /tmp/agent_conv_s8.txt 2>&1
./lulesh2.0 -s 12 -i 50 > /tmp/agent_conv_s12.txt 2>&1
./lulesh2.0 -s 16 -i 50 > /tmp/agent_conv_s16.txt 2>&1
./lulesh2.0 -s 20 -i 50 > /tmp/agent_conv_s20.txt 2>&1

# Run the agent's GCI analysis script if it exists
if [ -f /app/gci_analysis.py ]; then
    cd /app && python3 /app/gci_analysis.py 2>&1
fi

# Run pytest
cd /app
pytest /tests/test_state.py -v 2>&1
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
