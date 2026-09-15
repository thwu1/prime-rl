#!/bin/bash

# Deploy the hazard-pointer-based lock-free stack solution
cp /solution/lockfree_stack_solution.hpp /app/lockfree_stack.hpp

# Verify compilation
g++ -std=c++20 -pthread -O2 -o /tmp/verify_basic /tests/test_basic.cpp -I/app
if [ $? -ne 0 ]; then
    echo "ERROR: Solution does not compile"
    exit 1
fi

# Run basic correctness check
/tmp/verify_basic
if [ $? -ne 0 ]; then
    echo "ERROR: Solution fails basic tests"
    exit 1
fi

# Verify concurrent correctness
g++ -std=c++20 -pthread -O2 -o /tmp/verify_concurrent /tests/test_concurrent.cpp -I/app
/tmp/verify_concurrent
if [ $? -ne 0 ]; then
    echo "ERROR: Solution fails concurrent tests"
    exit 1
fi

echo "Solution deployed and verified successfully"
