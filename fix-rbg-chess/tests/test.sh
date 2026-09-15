#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Compile the draughts.rbg to C++ if the file exists
if [ -f /app/draughts.rbg ]; then
    /app/rbg/rbg2cpp/bin/rbg2cpp -o reasoner draughts.rbg 2>/app/rbg2cpp_err.log
    RBG_EXIT=$?
    if [ $RBG_EXIT -ne 0 ]; then
        echo "rbg2cpp compilation failed (exit code $RBG_EXIT)"
        cat /app/rbg2cpp_err.log
        mkdir -p /logs/verifier
        echo "0.0" > /logs/verifier/reward.txt
        exit 1
    fi

    # Compile the C++ perft test binary
    g++ -std=c++23 -O2 reasoner.cpp /app/rbg/rbg2cpp/test/perft.cpp -I. -o perft_test 2>/app/gcc_err.log
    GCC_EXIT=$?
    if [ $GCC_EXIT -ne 0 ]; then
        echo "C++ compilation failed (exit code $GCC_EXIT)"
        cat /app/gcc_err.log
        mkdir -p /logs/verifier
        echo "0.0" > /logs/verifier/reward.txt
        exit 1
    fi
fi

# Run pytest
pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
